#!/usr/bin/env python3
"""Compare live Tutor tool outcomes in isolated Atlas checkouts."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from evaluate_tutorbench import (
    BASE_URL, DATA, MAX_TOKENS, MODEL, ROOT, SEED, TEMPERATURE, isolated_settings,
    local_model, ok, patch_wire, read_json, response_text, sha_file, usage_summary,
    wait_turn, write_json,
)

SCENARIOS = ROOT / "evaluations/tutorbench/routing_tool_tasks.json"


def app_identity(root):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True)

    files = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "backend", "migrations")
    hashes = "".join(f"{name}:{sha_file(root / name)}\n" for name in sorted(set(files.split("\0")))
                     if name and (root / name).is_file())
    return {"commit": git("rev-parse", "HEAD").strip(), "app_sha256": sha256(hashes.encode()).hexdigest()}


def pdf_document(pages):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for line in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })})
        })
        text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 10 Tf 45 740 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def pin_domain_requests():
    from backend import model_providers

    original = model_providers.request_parts

    def request_parts(*args, **kwargs):
        url, headers, body = original(*args, **kwargs)
        if not url.startswith(BASE_URL + "/v1/"):
            raise ValueError("Tool evaluation only permits the local model")
        body.update(seed=SEED, temperature=TEMPERATURE)
        return url, headers, body

    return patch.object(model_providers, "request_parts", request_parts)


def payloads(turn, kind):
    return [event["payload"] for event in turn.get("events", []) if event["type"] == kind]


def setup_case(client, case, course_id, node_id):
    if case["kind"] == "retrieval":
        endpoint = f"/api/courses/{course_id}/sources"
        if case.get("page"):
            return ok(client.post(endpoint, files={
                "file": (case["title"], pdf_document(case["source_text"]), "application/pdf"),
            }))
        return ok(client.post(endpoint + "/text", json={
            "title": case["title"], "content": case["source_text"],
        }))
    if case["kind"] == "attempt":
        exercises = ok(client.get(f"/api/nodes/{node_id}/exercises"))
        exercise = exercises[case["exercise_index"]]
        attempt = ok(client.post(f"/api/exercises/{exercise['id']}/attempts", json={
            "answer": case["submitted_answer"], "request_id": "seed-actual-attempt",
        }))
        if attempt["passed"] or attempt["answer"] != case["submitted_answer"]:
            raise RuntimeError(f"{case['id']} must have a real incorrectly scored attempt")
        return attempt
    return None


def business_state(db, user_id, node_id):
    from backend.models import Attempt, Exercise, LearningEvidence, Node

    return {
        "exercises": {row[0] for row in db.query(Exercise.id).filter_by(user_id=user_id, node_id=node_id)},
        "attempts": db.query(Attempt).filter_by(user_id=user_id, node_id=node_id).count(),
        "evidence": db.query(LearningEvidence).filter_by(user_id=user_id, node_id=node_id).count(),
        "mastery": db.get(Node, node_id).mastery,
    }


def grade_retrieval(case, source, turn, results, answer):
    def matches(ref):
        if ref.get("source_id") != source["id"] or ref.get("source_version") != source["version"]:
            return False
        page = case.get("page")
        start = ref.get("page_start")
        end = ref.get("page_end") or start
        return (case["fact"] in ref.get("excerpt", "")
                and (page is None or (start is not None and start <= page <= end)))

    retrieved = [ref for result in results.get("retrieve_materials", []) for ref in result.get("sources", [])]
    citations = {ref.get("citation", index) for event in payloads(turn, "citations")
                 for index, ref in enumerate(event["citations"], 1) if matches(ref)}
    used = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
    return {"real_retrieval_returns_expected_source": any(map(matches, retrieved)),
            "answer_contains_source_fact": case["fact"] in answer,
            "answer_links_expected_source_version_and_page": bool(citations & used)}


def grade_attempt(attempt, results, answer):
    looked_up = [item for result in results.get("get_recent_attempts", []) for item in result.get("attempts", [])]
    return {"tool_returns_exact_real_attempt": any(item["id"] == attempt["id"] for item in looked_up),
            "answer_repeats_submitted_wrong_option": attempt["answer"] in answer}


def grade_practice(case, turn, results, before, after):
    cards = [card for event in payloads(turn, "question") for card in event["exercises"]]
    new_ids = after["exercises"] - before["exercises"]
    verified = [r for r in results.get("generate_practice", []) if (r.get("validation") or {}).get("status") == "passed"]
    return {"generated_and_verified_by_real_tool": len(verified) == 1,
            "exactly_requested_new_cards_persisted": (len(cards) == len(new_ids) == case["count"]
                                                      and {card["id"] for card in cards} == new_ids),
            "choice_card_has_no_private_answer_fields": (any(card["type"] == "choice" for card in cards)
                                                          and all(not ({"correct_answer", "explanation"} & card.keys()) for card in cards)),
            "generation_creates_no_attempt_or_mastery_evidence": all(before[k] == after[k] for k in ("attempts", "evidence", "mastery"))}


async def trial(client, case, require_route):
    from backend.database import SessionLocal

    owner = ok(client.post("/api/auth/register", json={
        "email": case["id"] + "@tool-routing-eval.invalid", "password": "LocalToolEvalOnly!2026",
        "full_name": "Tool routing learner",
    }))
    course = ok(client.post(f"/api/templates/{case['course']}/enroll"))
    course_id, node_id = course["id"], course["nodes"][0]["id"]
    seed = setup_case(client, case, course_id, node_id)
    with SessionLocal() as db:
        before = business_state(db, owner["id"], node_id)
    session = ok(client.post("/api/tutor/sessions", json={"course_id": course_id, "node_id": node_id}))
    started = perf_counter()
    turn = ok(client.post(f"/api/tutor/sessions/{session['id']}/turns", json={
        "content": case["prompt"], "request_id": case["id"], "capability": "tutor",
    }))
    try:
        turn = await wait_turn(client, turn["id"])
    except TimeoutError:
        client.post(f"/api/tutor/turns/{turn['id']}/cancel")
        turn = ok(client.get(f"/api/tutor/turns/{turn['id']}"))
    elapsed = round(perf_counter() - started, 3)
    answer = response_text(turn)
    route = [item.get("route") for item in payloads(turn, "answer_route")]
    outcomes, errors = {}, []
    for event in payloads(turn, "tool_result"):
        if event["result"].get("error"):
            errors.append({"tool": event["tool"], "error": event["result"]["error"]})
        else:
            outcomes.setdefault(event["tool"], []).append(event["result"])
    checks = {"turn_completed": turn["status"] == "completed"}
    if require_route:
        checks["full_agent_loop_selected"] = route == ["agent_loop"]
    with SessionLocal() as db:
        after = business_state(db, owner["id"], node_id)
    if case["kind"] == "retrieval":
        checks.update(grade_retrieval(case, seed, turn, outcomes, answer))
    elif case["kind"] == "attempt":
        checks.update(grade_attempt(seed, outcomes, answer))
    else:
        checks.update(grade_practice(case, turn, outcomes, before, after))
    if case["kind"] != "practice":
        checks["read_task_leaves_learning_state_unchanged"] = before == after
    usage = usage_summary(turn["events"])
    return {"id": case["id"], "kind": case["kind"], "passed": all(checks.values()),
            "checks": checks, "turn_status": turn["status"], "turn_error": turn.get("error"),
            "route": route, "tool_errors": errors, "answer": answer, "usage": usage,
            "elapsed_seconds": elapsed}


async def evaluate(output, require_route, cases):
    from fastapi.testclient import TestClient
    from backend.main import app

    path = output / "cases.json"
    results = read_json(path) if path.exists() else []
    done = {row["id"] for row in results}
    if len(done) != len(results) or not done <= {case["id"] for case in cases}:
        raise ValueError("Invalid tool task checkpoint")
    with TestClient(app), pin_domain_requests(), patch_wire():
        for case in cases:
            if case["id"] in done:
                continue
            # Reuse the running app but isolate cookies and course data for every case.
            client = TestClient(app)
            try:
                result = await trial(client, case, require_route)
            finally:
                client.close()
            results.append(result)
            write_json(path, results)
            print(f"{len(results)}/{len(cases)} {case['id']} {'passed' if result['passed'] else 'failed'}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DATA / "routing-tools" / "current")
    parser.add_argument("--require-route", action="store_true", help="Check new answer_route telemetry")
    args = parser.parse_args()
    root = args.atlas_source.resolve()
    output = args.output.resolve()
    cases = read_json(SCENARIOS)
    assert Counter(case["kind"] for case in cases) == {"retrieval": 2, "attempt": 2, "practice": 2}
    assert len({case["id"] for case in cases}) == len(cases)
    metadata = {"app": app_identity(root), "model": local_model(MODEL), "temperature": TEMPERATURE,
                "seed": SEED, "max_tokens_per_tutor_request": MAX_TOKENS, "scenario_sha256": sha_file(SCENARIOS),
                "runner_sha256": sha_file(Path(__file__)), "require_route": args.require_route}
    metadata_path = output / "run.json"
    if metadata_path.exists() and read_json(metadata_path) != metadata:
        raise ValueError("Evaluation conditions changed; choose a new output directory")
    write_json(metadata_path, metadata)
    sys.path.insert(0, str(root))
    with TemporaryDirectory(prefix="atlas-routing-tools-") as scratch:
        isolated_settings(scratch)
        results = asyncio.run(evaluate(output, args.require_route, cases))
    report = {**metadata, "n": len(results), "passed": sum(row["passed"] for row in results),
              "by_kind": {kind: {"passed": sum(row["passed"] for row in results if row["kind"] == kind),
                                 "total": count} for kind, count in Counter(row["kind"] for row in results).items()},
              "usage": {key: sum(row["usage"][key] for row in results)
                        for key in ("calls", "usage_known", "prompt_tokens", "completion_tokens")},
              "failures": [{"id": row["id"], "failed_checks": [key for key, passed in row["checks"].items() if not passed],
                            "turn_error": row["turn_error"], "tool_errors": row["tool_errors"]}
                           for row in results if not row["passed"]]}
    write_json(output / "summary.json", report)
    print(f"Tool-required tasks: {report['passed']}/{report['n']} passed; {output / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
