#!/usr/bin/env python3
"""Run Atlas's course-level cross-session memory comparison with local Qwen."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from evaluate_tutorbench import (
    DATA, MAX_TOKENS, MODEL, ROOT, SEED, TEMPERATURE, isolated_settings, local_model, ok, patch_wire, read_json,
    response_text, sha_file, usage_summary, wait_turn, write_json,
)

TASKS = ROOT / "evaluations/tutorbench/learning_scenarios.json"
ARMS = ("recall_off", "recall_on")
PRACTICE_FILLER_COUNT = 5

def normalized(text):
    return re.sub(r"[\s。．]+", "", text).casefold()

def read_answer(text):
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    if isinstance(value, dict) and isinstance(value.get("record"), str) and isinstance(value.get("next"), str):
        return value
    return {}

def ask_prompt(case):
    description = {"chat": "旧会话中我自己的原话", "note": "旧笔记中的原文", "practice": "较早那次练习的错误选项"}[case["source"]]
    options = "\n".join(f"{key}. {text}" for key, text in case["options"].items())
    return (
        f"继续复习「{case['topic']}」。请查找{description}，原样放在 record。"
        "结合该记录从下面选择一个下一步练习，只用字母填 next。没有可靠记录时 record 和 next 都填空字符串，禁止猜测。"
        '只输出 JSON：{"record":"原文","next":"选项字母"}。\n' + options
    )

def create_session(client, course_id):
    return ok(client.post("/api/tutor/sessions", json={"course_id": course_id}))["id"]

async def turn(client, course_id, content, request_id, capability="qa"):
    session = create_session(client, course_id)
    saved = ok(client.post(f"/api/tutor/sessions/{session}/turns", json={
        "content": content, "request_id": request_id, "capability": capability,
    }))
    return session, await wait_turn(client, saved["id"])

def recall_ablation():
    from backend.agent.telemetry import _scope
    from backend.database import SessionLocal
    from backend.memory import service
    from backend.models import TutorTurn

    original = service.recall
    def controlled(db, user_id, query, course_id=None, limit=8):
        current = _scope.get()
        if current:
            with SessionLocal() as lookup:
                request_id = lookup.query(TutorTurn.request_id).filter_by(id=current.turn_id).scalar()
            if request_id and request_id.startswith("memory-off/"):
                return {"memories": [], "profile": {"status": "unavailable", "groups": []}}
        return original(db, user_id, query, course_id, limit)
    return patch.object(service, "recall", controlled)

async def record_input(client, case, course):
    course_id = course["id"]
    text = case["record"]
    if case["source"] == "chat":
        session_id, response = await turn(
            client, course_id, text + " 这是我的学习记录，只回复收到。", "setup/" + case["id"],
        )
        return {"kind": "turn", "id": response["id"], "session": session_id, "status": response["status"]}
    if case["source"] == "note":
        note = ok(client.post("/api/notes", json={
            "title": case["topic"] + "复习笔记", "content": text, "course_id": course_id,
        }))
        return {"kind": "note", "id": note["id"], "status": "saved"}

    node_id = course["nodes"][0]["id"]
    exercises = ok(client.get(f"/api/nodes/{node_id}/exercises"))
    target = next(e for e in exercises if text in e["options"])
    filler = next(e for e in exercises if e["id"] != target["id"])
    graded = ok(client.post(f"/api/exercises/{target['id']}/attempts", json={
        "answer": text, "request_id": "setup/" + case["id"],
    }))
    if graded["passed"] or graded["answer"] != text:
        raise ValueError("Expected a real recorded incorrect attempt")
    for i in range(PRACTICE_FILLER_COUNT):
        ok(client.post(f"/api/exercises/{filler['id']}/attempts", json={
            "answer": filler["options"][0], "request_id": f"filler/{i}",
        }))
    return {"kind": "assessment", "id": graded["id"], "status": "graded", "score": graded["score"]}

def matching_source(client, case, source, course_id):
    fields = {"turn": "turn_id", "note": "note_id", "assessment": "attempt_id"}
    all_memories = ok(client.get("/api/me/memory/recall", params={"course_id": course_id, "q": ask_prompt(case)}))
    for memory in all_memories["memories"]:
        if normalized(case["record"]) not in normalized(memory["content"]):
            continue
        detail = ok(client.get(f"/api/me/memories/{memory['id']}"))
        if detail["memory"]["origin"] != "record" or detail["memory"]["source_status"] != "valid":
            continue
        evidence = next((item for item in detail["evidence"] if item["kind"] == source["kind"]
                         and item.get(fields[source["kind"]]) == source["id"]), None)
        if evidence:
            return {"id": memory["id"], "evidence": evidence}
    return None

async def evaluate(cases, output, metadata):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.tutor.runner import worker_loop

    path = output / "memory-cases.json"
    results = read_json(path) if path.exists() else []
    done = {case["id"] for case in results}
    if len(done) != len(results) or not done <= {case["id"] for case in cases}:
        raise ValueError("Invalid cross-session checkpoint")
    with TestClient(app) as client, recall_ablation(), patch_wire():
        stop = asyncio.Event()
        worker = asyncio.create_task(worker_loop(stop))
        try:
            for index, case in enumerate(cases):
                if case["id"] in done:
                    continue
                ok(client.post("/api/auth/register", json={
                    "email": f"{case['id']}@evaluation.invalid", "password": "AtlasMemoryEvalOnly!2026",
                    "full_name": "Cross-session learner",
                }))
                course = ok(client.post(f"/api/templates/{case['course']}/enroll"))
                course_id = course["id"]
                source = await record_input(client, case, course)
                organized = ok(client.post("/api/me/memory/organize", json={
                    "course_id": course_id, "request_id": "organize/" + case["id"],
                }))
                evidence = matching_source(client, case, source, course_id)
                arms = {}
                for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
                    setting = "off" if arm == "recall_off" else "on"
                    session, response = await turn(client, course_id, ask_prompt(case), f"memory-{setting}/" + case["id"])
                    if session == source.get("session"):
                        raise ValueError("Probe reused the original chat")
                    answer = response_text(response)
                    decoded = read_answer(answer) if response["status"] == "completed" else {}
                    correct = bool(decoded) and normalized(decoded["record"]) == normalized(case["record"])
                    next_step = bool(decoded) and decoded["next"].strip().upper() == case["next"]
                    recalls = [e["payload"]["memory_count"] for e in response["events"] if e["type"] == "memory_recalled"]
                    if arm == "recall_off" and any(recalls):
                        raise ValueError("Memory-off control exposed recalled memory")
                    arms[arm] = {
                        "session": session, "status": response["status"], "answer": answer,
                        "record_exact": correct, "next_correct": next_step, "joint_pass": correct and next_step,
                        "recall_counts": recalls, "usage": usage_summary(response["events"]),
                    }
                results.append({"id": case["id"], "source_kind": case["source"], "source": source,
                                "organized": organized, "source_verified": evidence, "arms": arms})
                write_json(path, results)
                print(f"Cross-session {len(results)}/{len(cases)} {case['id']}", flush=True)
        finally:
            stop.set()
            await worker
    counts = {
        arm: {metric: sum(case["arms"][arm][metric] for case in results)
              for metric in ("record_exact", "next_correct", "joint_pass")}
        for arm in ARMS
    }
    report = {**metadata, "n": len(results),
              "source_verified": sum(bool(case["source_verified"]) for case in results),
              "by_arm": counts, "filler_attempts_per_practice_case": PRACTICE_FILLER_COUNT}
    write_json(output / "memory-summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA / "run")
    args = parser.parse_args()
    cases = read_json(TASKS)
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model": local_model(MODEL), "scenario_sha256": sha_file(TASKS),
        "runner_sha256": sha_file(Path(__file__)),
        "max_tokens_per_call": MAX_TOKENS, "temperature": TEMPERATURE, "seed": SEED,
    }
    metadata_path = args.output / "memory-run.json"
    if metadata_path.exists() and read_json(metadata_path) != metadata:
        raise ValueError("Cross-session conditions changed; choose a new output directory")
    write_json(metadata_path, metadata)
    with TemporaryDirectory(prefix="atlas-learning-memory-") as scratch:
        isolated_settings(scratch)
        asyncio.run(evaluate(cases, args.output, metadata))

if __name__ == "__main__":
    main()
