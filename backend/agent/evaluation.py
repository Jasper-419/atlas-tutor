"""Small task harness with real Atlas API/state and an explicit model fixture.

Only standard-library imports are allowed before the isolated worker starts.
Never import backend.config/database/main in the parent process.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
TASK_FILE = ROOT / "evaluations/agent_tasks.json"
MODEL_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "DEEPSEEK_API_KEY", "LLM_MODEL")
PRACTICE_FOCUS = "Python 赋值、对象引用与列表可变性"
PRIVATE_REFERENCE = "在 Python 中，b = a 只建立名字到同一对象的新绑定，不会复制列表；若通过 a 修改该可变对象，b 会观察到同一对象的变化。"


def redact(value, secrets=()):
    text = str(value)
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    for name, secret in os.environ.items():
        if any(word in name for word in ("KEY", "TOKEN", "PASSWORD", "SECRET")) and len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", text)


def load_tasks(mode, selection=None):
    tasks = json.loads(TASK_FILE.read_text())["tasks"]
    if selection:
        wanted = {item.strip() for part in selection for item in part.split(",") if item.strip()}
        unknown = wanted - {task["id"] for task in tasks}
        if unknown:
            raise ValueError("Unknown cases: " + ", ".join(sorted(unknown)))
        return [task for task in tasks if task["id"] in wanted]
    return [task for task in tasks if mode == "fixture" or task["live_default"]]


def isolated_env(folder, mode):
    folder = str(Path(folder).resolve())
    env = dict(os.environ)
    # .env is read only for the five model settings in explicit live mode.
    if mode == "live":
        from dotenv import dotenv_values
        values = dotenv_values(ROOT / ".env")
        for name in MODEL_ENV:
            if name not in env and values.get(name):
                env[name] = str(values[name])
    else:
        env.update(OPENAI_API_KEY="evaluation-fixture-not-a-real-credential", OPENAI_BASE_URL="http://127.0.0.1:1/v1", OPENAI_MODEL="fixture-script", DEEPSEEK_API_KEY="")
    env.update(
        PYTHON_DOTENV_DISABLED="1", ATLAS_EVAL_WORKER="1", ATLAS_EVAL_ROOT=folder,
        ATLAS_DATA_DIR=folder, DATABASE_URL="sqlite:///" + str(Path(folder) / "atlas.db"),
        ATLAS_CHECKPOINT_PATH=str(Path(folder) / "checkpoints.db"), CHECKPOINT_DATABASE_URL="",
        ATLAS_CREDENTIALS_KEY="", WORKER_MODE="disabled", COOKIE_SECURE="false",
        EMBEDDING_MODEL="", EMBEDDING_API_KEY="", TAVILY_API_KEY="",
    )
    return env


def markdown_report(report):
    lines = ["# Atlas Agent evaluation", "", f"- Mode: **{report['mode']}**", f"- Evidence: {report['evidence_label']}", f"- Created: {report['created_at']}", f"- Model: {report.get('model', 'not available')}", "- Each selected task has one trial; this is not a statistically stable model score.", "", "| Task | Result | Checks | Wall time (ms) | Model/tool calls |", "| --- | --- | --- | ---: | --- |"]
    for case in report["cases"]:
        checks = case.get("checks", [])
        usage = case.get("usage", {})
        lines.append(f"| {case['id']} | {case['status']} | {sum(bool(c['passed']) for c in checks)}/{len(checks)} | {case.get('duration_ms', 0)} | {usage.get('model_calls', '—')}/{usage.get('tool_calls', '—')} |")
    lines += ["", "Fixture passes are protocol/state checks with scripted provider responses, never model ability scores. Live failures and unexpected outcomes are retained.", ""]
    for case in report["cases"]:
        lines += [f"## {case['id']}: {case['name']}", ""]
        for check in case.get("checks", []):
            lines.append(f"- {'PASS' if check['passed'] else 'FAIL'}: {check['criterion']}")
        if case.get("error"):
            lines += ["", "Error: " + case["error"]]
        lines += ["", "```json", json.dumps({key: case.get(key) for key in ("observations", "usage", "trace")}, ensure_ascii=False, indent=2), "```", ""]
    lines += ["## Limits", "", *["- " + value for value in report["limitations"]], ""]
    return "\n".join(lines)


def write_reports(report, output):
    path = Path(output).expanduser().resolve() if output else ROOT / "data/agent-evals" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if path.suffix.lower() in {".json", ".md"}:
        json_path, md_path = path.with_suffix(".json"), path.with_suffix(".md")
    else:
        json_path, md_path = path / "report.json", path / "report.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)) + "\n")
    md_path.write_text(redact(markdown_report(report)))
    return json_path, md_path


class FixtureProvider:
    """Only substitutes external model responses; no tools/state are substituted."""
    case = ""
    foreign_course_id = ""
    practice_serial = 0

    @staticmethod
    def call(identifier, name, arguments):
        return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}

    async def round(self, config, messages, tools, user_id):
        last_user = max(i for i, message in enumerate(messages) if message["role"] == "user")
        results = [m for m in messages[last_user + 1:] if m["role"] == "tool"]
        calls, output = [], "本次操作已结束，请以界面保存的实际结果为准。"
        grading = any("以下是服务器对用户刚提交答案的真实评分" in m.get("content", "") for m in messages[last_user + 1:])
        if grading:
            output = "已收到真实提交的答案，评分与学习证据由服务器记录。"
        elif self.case == "document_qa":
            if not results:
                calls = [self.call("retrieve-1", "retrieve_materials", {"query": "定义与例子的区别"})]
            else:
                result = json.loads(results[-1]["content"])
                sources = result.get("sources", [])
                number = sources[0].get("citation", 1) if sources else 1
                output = f"定义说明适用范围与必要约束，例子是满足条件的具体实例，不能以单个例子代替完整定义。[{number}]"
        elif self.case in {"practice", "answer_idempotency"} and not results:
            calls = [self.call("practice-1", "generate_practice", {"count": 2, "focus": PRACTICE_FOCUS, "difficulty": "adaptive"})]
        elif self.case == "scope_refusal":
            if not results:
                calls = [self.call("scope-1", "generate_practice", {"count": 2, "focus": "定义与例子", "difficulty": "adaptive"})]
            else:
                output = "请说明要练习哪个概念的定义与例子；当前节点是Python赋值与对象引用。"
        elif self.case == "verified_solve":
            if not results:
                calls = [self.call("solve-plan", "solve_plan", {"goal": "计算1到100的整数和", "steps": [{"id": "sum", "title": "运行求和并核对", "method": "python"}]})]
            elif len(results) == 1:
                calls = [self.call("solve-python", "python_check", {"step_id": "sum", "code": "total=sum(range(1,101))\nprint(total)", "checks": [{"expression": "total", "expected": 5050}]})]
            elif len(results) == 2:
                receipt = json.loads(results[-1]["content"])["execution"]
                calls = [self.call("solve-step", "solve_finish_step", {"step_id": "sum", "explanation": "真实运行得到5050，所列检查通过。", "evidence_id": receipt["evidence_id"]})]
            elif len(results) == 3:
                calls = [self.call("solve-finish", "solve_finish", {"summary": "1到100的整数和是5050；已运行求和并核对列出的检查。"})]
            else:
                output = "1到100的整数和是5050；程序已运行，所列检查通过。"
        elif self.case == "approval_boundary" and not results:
            calls = [self.call("path-1", "propose_path_change", {"reason": "首节点17分钟，增加迁移练习，等待界面确认。"})]
        elif self.case == "cross_user":
            if not results:
                calls = [self.call("foreign-1", "select_context", {"course_id": self.foreign_course_id})]
            else:
                output = "工具拒绝了其他用户的课程，未读取该课程资料。"
        elif self.case == "qa_write_denied":
            if not results:
                calls = [self.call("denied-1", "generate_practice", {"count": 2, "focus": "定义与例子"}), self.call("denied-2", "remember_memory", {"content": "我偏好例子。", "category": "preference"})]
            else:
                output = "当前只读权限不允许生成题卡或保存偏好。"
        elif self.case == "tool_failure_recovery":
            if not results:
                calls = [self.call("bad-node-1", "get_learning_state", {"node_id": "missing-eval-node"})]
            elif len(results) == 1:
                calls = [self.call("good-node-1", "get_learning_state", {})]
            else:
                output = "查询不存在节点失败，随后已读取当前节点的真实学习状态。"
        message = {"role": "assistant", "content": "" if calls else output}
        if calls:
            message["tool_calls"] = calls
        else:
            yield {"kind": "text", "text": output}
        yield {"kind": "result", "message": message, "usage": {}}

    async def complete(self, messages, user_id, step, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if step == "practice_contract_scope":
            ambiguous = payload["request"]["focus"] == "定义与例子"
            return {"context_hash": payload["context_hash"], "decision": "uncertain" if ambiguous else "in_scope",
                "interpreted_focus": "未明确的概念" if ambiguous else PRACTICE_FOCUS,
                "reason": "未说明具体概念，需要澄清。" if ambiguous else "赋值、引用与可变性属于节点范围。",
                "evidence": [] if ambiguous else [{"source_ref": "node_scope", "quote": payload["node"]["title"] + "\n" + payload["node"]["objective"]}]}
        if step == "practice_contract_verify":
            source = payload["sources"][0]
            return {"context_hash": payload["context_hash"], "items_hash": payload["items_hash"],
                "items": [{"index": index, "focus": "pass", "answer_key": "pass", "source_support": "pass",
                    "reason": "独立检查赋值不会复制列表，两个名字共享同一对象；选择题唯一正确，开放答案符合绑定与可变性。",
                    "evidence": [{"source_ref": source["source_ref"], "quote": source["text"][:1000]}]}
                    for index in range(len(payload["exercises"]))]}
        if step == "adaptive_practice":
            self.practice_serial += 1
            return {"exercises": [{"type": "choice" if i % 2 == 0 else "open", "prompt": f"第{self.practice_serial}批第{i+1}题：Python 中 b = a 后修改列表为何会被两个名字观察到？", "options": ["两个名字引用同一个列表对象", "赋值会复制列表"] if i % 2 == 0 else [], "correct_answer": "两个名字引用同一个列表对象" if i % 2 == 0 else PRIVATE_REFERENCE, "explanation": "赋值只建立绑定，不复制列表；共享可变对象的修改可通过两个名字观察。", "skill_type": "concept"} for i in range(payload["count"])]}
        if step == "path_change_preview":
            first = payload["current_path"]["nodes"][0]
            return {"title": "定义与例子的学习路径", "nodes": [{"key": "base", **{key: first[key] for key in ("title", "summary", "objective", "difficulty")}, "estimated_minutes": 17, "prerequisites": []}, {"key": "transfer", "title": "迁移练习", "summary": "用定义判断新例子", "objective": "解释新实例的概念边界", "estimated_minutes": 23, "difficulty": "beginner", "prerequisites": ["base"]}]}
        raise AssertionError("Unconfigured fixture external completion: " + step)


def run_worker(tasks, mode, timeout):
    # Verify isolation before importing any module that creates an engine.
    root = Path(os.environ.get("ATLAS_EVAL_ROOT", "")).resolve()
    expected_db = "sqlite:///" + str(root / "atlas.db")
    if os.environ.get("ATLAS_EVAL_WORKER") != "1" or not root.name.startswith("atlas-agent-eval-") or os.environ.get("DATABASE_URL") != expected_db or os.environ.get("ATLAS_DATA_DIR") != str(root):
        raise RuntimeError("Evaluation worker requires an isolated temporary environment")
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.database import SessionLocal
    from backend.models import Attempt, Course, Exercise, LearningEvidence, Memory, User
    from backend.tutor import paths
    from backend.connections import resolve_model_config

    def ok(response, status=200):
        if response.status_code != status:
            raise AssertionError(f"Expected HTTP {status}, got {response.status_code}: {response.text[:600]}")
        return response.json()

    def wait(client, identifier):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            turn = ok(client.get(f"/api/tutor/turns/{identifier}"))
            if turn["status"] in {"completed", "failed", "cancelled", "waiting_confirmation", "waiting_input"}:
                return turn
            time.sleep(.05)
        client.post(f"/api/tutor/turns/{identifier}/cancel")
        raise TimeoutError(f"Task exceeded {timeout}s; cancellation requested")

    def counts():
        with SessionLocal() as db:
            return {model.__tablename__: db.query(model).count() for model in (Exercise, Attempt, LearningEvidence, Memory)}

    def snapshot(course_id):
        with SessionLocal() as db:
            return paths.course_snapshot(db, db.get(Course, course_id))

    def call_results(turn):
        return [event["payload"] for event in turn.get("events", []) if event["type"] == "tool_result"]

    fixture = FixtureProvider()
    report = {"schema_version": 1, "mode": mode, "created_at": datetime.now(timezone.utc).isoformat(), "evidence_label": "scripted provider + real API/database/domain contracts; NOT a model score" if mode == "fixture" else "live configured model + real API/database/domain; one trial per task", "cases": [], "limitations": ["8 narrow tasks, no held-out or adversarial corpus; no statistical claims.", "String/reference checks verify minimal relevance and resolvability, not expert explanation quality.", "Fixture model output is scripted; token cost and model quality cannot be inferred.", "Tool failure task covers a real invalid-resource error and model correction, not process-crash recovery or transient network retry.", "No distributed exactly-once guarantee, load benchmark, mobile check, or external side-effect provider is evaluated.", "Nested operation usage remains unknown when a fixture/provider supplies no measured token counts."]}
    with ExitStack() as stack:
        if mode == "fixture":
            stack.enter_context(patch("backend.tutor.runner.model_round", fixture.round))
            stack.enter_context(patch("backend.learning.complete", fixture.complete))
            stack.enter_context(patch("backend.practice_contracts.complete", fixture.complete))
            stack.enter_context(patch("backend.tutor.paths.complete", fixture.complete))
        owner = stack.enter_context(TestClient(app))
        other = TestClient(app)
        stack.callback(other.close)
        users = []
        for client, name in ((owner, "owner"), (other, "other")):
            users.append(ok(client.post("/api/auth/register", json={"email": name + "@agent-eval.test", "password": "AtlasEval123!", "full_name": name})))
        template = ok(owner.get("/api/templates"))[0]
        course = ok(owner.post(f"/api/templates/{template['id']}/enroll"))
        foreign = ok(other.post(f"/api/templates/{template['id']}/enroll"))
        course_id, node_id = course["id"], course["nodes"][0]["id"]
        source = ok(owner.post(f"/api/courses/{course_id}/sources/text", json={"title": "定义与例子：评估资料", "content": "定义说明概念的适用范围与必要约束。例子是满足概念条件的具体实例，单个例子不能代替完整定义。判断新实例时需要核对定义中的所有必要条件，并识别边界。"}))
        fixture.foreign_course_id = foreign["id"]
        # Do not disclose credentials, base URL, cookies, or checkpoint messages.
        with SessionLocal() as db:
            user = db.query(User).filter_by(email="owner@agent-eval.test").one()
            user_id = user.id
        config = resolve_model_config(user_id)
        report["model"] = config.model
        if mode == "live" and not config.configured:
            raise RuntimeError("Live mode requires OPENAI_API_KEY or DEEPSEEK_API_KEY in environment/.env; saved business-database connections are intentionally not read")
        for task in tasks:
            started = time.monotonic()
            fixture.case = task["id"]
            item = {"id": task["id"], "name": task["name"], "profile": task["profile"], "checks": [], "observations": {}, "turn_ids": []}
            def check(criterion, passed):
                item["checks"].append({"criterion": criterion, "passed": bool(passed)})
            try:
                session = ok(owner.post("/api/tutor/sessions", json={"course_id": course_id, "node_id": node_id, "mode": "outline" if task["id"] == "approval_boundary" else "study"}))
                before, path_before = counts(), snapshot(course_id)
                prompt = task["prompt"].replace("{foreign_course_id}", foreign["id"])
                turn = ok(owner.post(f"/api/tutor/sessions/{session['id']}/turns", json={"content": prompt, "request_id": task["id"], "profile": task["profile"]}))
                item["turn_ids"].append(turn["id"])
                turn = wait(owner, turn["id"])
                item["observations"].update(input=prompt, status=turn["status"], output=turn["output"][:1600], tool_results=call_results(turn))
                expected = {"waiting_confirmation"} if task["id"] == "approval_boundary" else {"completed", "waiting_input"} if task["id"] == "scope_refusal" else {"completed"}
                check("turn reaches expected terminal/pause state", turn["status"] in expected)
                events = turn.get("events", [])
                results = call_results(turn)
                if task["id"] == "document_qa":
                    citations = [c for e in events if e["type"] == "citations" for c in e["payload"].get("citations", [])]
                    check("retrieval tool returns real sources", any(r["tool"] == "retrieve_materials" and r["result"].get("sources") for r in results))
                    check("citation resolves to owned source/version", any(c["source_id"] == source["id"] and c.get("source_version") == 1 for c in citations))
                    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", turn["output"])}
                    available = {c.get("citation", index) for index, c in enumerate(citations, 1)}
                    check("answer has resolvable citations and relevant concepts", bool(numbers) and numbers <= available and "定义" in turn["output"] and "例子" in turn["output"])
                elif task["id"] in {"practice", "answer_idempotency"}:
                    questions = [q for e in events if e["type"] == "question" for q in e["payload"].get("exercises", [])]
                    item["observations"]["questions"] = questions
                    check("exactly two question cards from generate_practice", len(questions) == 2 and any(r["tool"] == "generate_practice" and not r["result"].get("error") for r in results))
                    check("public question payload hides answer/explanation", bool(questions) and all("correct_answer" not in q and "explanation" not in q for q in questions))
                    with SessionLocal() as db:
                        stored = [db.get(Exercise, q["id"]) for q in questions]
                        check("cards exist in real database", bool(stored) and all(q is not None and q.user_id == user_id for q in stored))
                    check("generation creates no attempts or learning evidence", all(counts()[name] == before[name] for name in (Attempt.__tablename__, LearningEvidence.__tablename__)))
                    check("generation does not change mastery", {n["id"]: n["mastery"] for n in snapshot(course_id)["nodes"]} == {n["id"]: n["mastery"] for n in path_before["nodes"]})
                    if mode == "fixture":
                        check("fixture private answer reference absent from public turn", PRIVATE_REFERENCE not in json.dumps(turn, ensure_ascii=False))
                    if task["id"] == "answer_idempotency":
                        choice = next((q for q in questions if q["type"] == "choice"), None)
                        check("generated a choice question for real answer submission", choice is not None)
                        if choice:
                            baseline = counts()
                            body = {"exercise_id": choice["id"], "answer": "A", "request_id": "real-answer-1"}
                            endpoint = f"/api/tutor/sessions/{session['id']}/answers"
                            first = ok(owner.post(endpoint, json=body))
                            repeated = ok(owner.post(endpoint, json=body))
                            check("same submitted request returns same turn", first["id"] == repeated["id"])
                            answer = wait(owner, first["id"])
                            item["turn_ids"].append(first["id"])
                            check("real server assessment event exists", any(e["type"] == "assessment" and e["payload"].get("answer") == "A" for e in answer.get("events", [])))
                            check("exactly one Attempt and one LearningEvidence added", all(counts()[name] == baseline[name] + 1 for name in (Attempt.__tablename__, LearningEvidence.__tablename__)))
                            check("changed answer with same request_id rejected", owner.post(endpoint, json={**body, "answer": "B"}).status_code == 409)
                            item["observations"]["answer_turn_status"] = answer["status"]
                elif task["id"] == "scope_refusal":
                    questions = [q for e in events if e["type"] == "question" for q in e["payload"].get("exercises", [])]
                    refusal = any(r["tool"] == "generate_practice" and r["result"].get("error") for r in results)
                    clarification = turn["status"] == "waiting_input" and (turn.get("pending_action") or {}).get("kind") == "ask_user"
                    check("ambiguous focus produces refusal or an explicit clarification pause", refusal or clarification)
                    check("no unrelated question cards or exercises persisted", not questions and counts()[Exercise.__tablename__] == before[Exercise.__tablename__])
                    check("no attempts or mastery evidence created", all(counts()[name] == before[name] for name in (Attempt.__tablename__, LearningEvidence.__tablename__)))
                    check("mastery remains unchanged", {n["id"]: n["mastery"] for n in snapshot(course_id)["nodes"]} == {n["id"]: n["mastery"] for n in path_before["nodes"]})
                elif task["id"] == "approval_boundary":
                    check("preview produces no path write", snapshot(course_id) == path_before)
                    action = turn.get("pending_action") or {}
                    check("exact proposal displayed", action.get("kind") == "path_change" and bool(action.get("changes")))
                    if action:
                        endpoint = f"/api/tutor/turns/{turn['id']}/respond"
                        check("wrong confirmation action rejected", owner.post(endpoint, json={"approved": True, "action_id": "wrong-action"}).status_code == 422)
                        ok(owner.post(endpoint, json={"approved": False, "action_id": action["action_id"]}))
                        turn = wait(owner, turn["id"])
                        check("reject leaves exact course snapshot unchanged", snapshot(course_id) == path_before)
                elif task["id"] == "cross_user":
                    for endpoint in (f"/api/tutor/sessions/{session['id']}", f"/api/tutor/turns/{turn['id']}", f"/api/agent/runs/agent/{turn['id']}"):
                        check("cross-user GET rejected: " + endpoint.split("/api/")[-1], other.get(endpoint).status_code == 404)
                    check("foreign course cannot be selected via session API", owner.post("/api/tutor/sessions", json={"course_id": foreign["id"]}).status_code == 404)
                    check("tool-level cross-user context selection denied", any(r["tool"] == "select_context" and r["result"].get("error") for r in results))
                elif task["id"] == "qa_write_denied":
                    catalog = ok(owner.get("/api/agent/tools", params={"profile": "qa"}))
                    check("qa catalog excludes business writes", bool(catalog["tools"]) and all(t["access"] in {"read", "state"} for t in catalog["tools"]) and not {"generate_practice", "remember_memory"} & {t["name"] for t in catalog["tools"]})
                    check("attempted write denied by dispatcher", any(r["tool"] in {"generate_practice", "remember_memory"} and r["result"].get("error") for r in results))
                    check("business write counts unchanged", counts() == before)
                elif task["id"] == "tool_failure_recovery":
                    state_results = [r["result"] for r in results if r["tool"] == "get_learning_state"]
                    check("invalid resource error returned to model", bool(state_results) and bool(state_results[0].get("error")))
                    check("subsequent corrected state read succeeds", len(state_results) >= 2 and not state_results[-1].get("error") and bool(state_results[-1].get("course")))
                elif task["id"] == "verified_solve":
                    executions = [r["result"]["execution"] for r in results if r["tool"] == "python_check" and r["result"].get("execution")]
                    passed = [e for e in executions if e.get("status") == "passed"]
                    check("real restricted Python execution and explicit checks pass", bool(passed) and any(e.get("stdout", "").strip() == "5050" and e.get("checks") and all(c.get("passed") is True for c in e["checks"]) for e in passed))
                    check("plan/evidence/finish tools all executed", {"solve_plan", "python_check", "solve_finish_step", "solve_finish"} <= {r["tool"] for r in results})
                    check("capability completion records verified steps", turn.get("capability") == "solve" and (turn.get("result") or {}).get("outcome") == "verified" and (turn.get("result") or {}).get("verified_steps", 0) >= 1)
                    check("solving does not create learning evidence or practice writes", counts() == before)
                item["observations"]["row_delta"] = {name: counts()[name] - before[name] for name in before}
                # All task turns, including actual answer continuation, are inspected.
                traces = []
                for identifier in item["turn_ids"]:
                    response = owner.get(f"/api/agent/runs/agent/{identifier}")
                    check("authenticated trace available", response.status_code == 200)
                    if response.status_code == 200:
                        trace = response.json()
                        traces.append(trace)
                item["trace"] = [{"run": t.get("run"), "policy": t.get("policy"), "spans": t.get("spans"), "limitations": t.get("limitations")} for t in traces]
                item["usage"] = {}
                for name in ("prompt_tokens", "completion_tokens", "model_calls", "tool_calls", "retries"):
                    values = [t.get("usage", {}).get(name) for t in traces]
                    item["usage"][name] = sum(values) if values and all(v is not None for v in values) else None
                item["usage"]["tokens_measured"] = mode == "live" and all(item["usage"][key] is not None for key in ("prompt_tokens", "completion_tokens"))
                if task["id"] == "document_qa":
                    kinds = {span["kind"] for trace in traces for span in trace.get("spans", [])}
                    check("model and tool spans recorded", {"model", "tool"} <= kinds)
                if task["id"] == "tool_failure_recovery":
                    check("failed tool span retained", any(s.get("kind") == "tool" and s.get("status") in {"error", "failed"} for t in traces for s in t.get("spans", [])))
            except Exception as exc:
                item["error"] = redact(type(exc).__name__ + ": " + str(exc))[:2000]
            item["duration_ms"] = int((time.monotonic() - started) * 1000)
            item["status"] = "passed" if item["checks"] and all(c["passed"] for c in item["checks"]) and not item.get("error") else "failed"
            report["cases"].append(item)
        from backend.models import Trace
        with SessionLocal() as db:
            rows = db.query(Trace).filter_by(user_id=user_id).all()
            report["domain_model_usage"] = {"trace_count": len(rows), "prompt_tokens": sum(r.prompt_tokens or 0 for r in rows), "completion_tokens": sum(r.completion_tokens or 0 for r in rows), "steps": sorted({r.step for r in rows}), "tokens_measured": mode == "live"}
    report["summary"] = {"passed": sum(c["status"] == "passed" for c in report["cases"]), "total": len(report["cases"])}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--cases", nargs="+", help="Task IDs, space/comma separated; live default is four tasks")
    parser.add_argument("--output", help="Report directory or .json/.md path; both formats are written")
    parser.add_argument("--timeout", type=float, default=180, help="Seconds per turn (live may call the model multiple times)")
    parser.add_argument("--worker-output", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        tasks = load_tasks(args.mode, args.cases)
    except ValueError as exc:
        parser.error(str(exc))
    if args.worker_output:
        report = run_worker(tasks, args.mode, args.timeout)
        Path(args.worker_output).write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)))
        return 0
    with tempfile.TemporaryDirectory(prefix="atlas-agent-eval-") as folder:
        worker_output = Path(folder) / "worker-report.json"
        command = [sys.executable, str(ROOT / "scripts/evaluate_agent.py"), "--mode", args.mode, "--timeout", str(args.timeout), "--worker-output", str(worker_output), "--cases", *[task["id"] for task in tasks]]
        worker_env = isolated_env(folder, args.mode)
        result = subprocess.run(command, cwd=ROOT, env=worker_env, capture_output=True, text=True)
        if result.returncode or not worker_output.exists():
            # Worker output may contain provider data; never dump its stdout/stderr.
            print("Evaluation worker could not start or finish; no score produced. " + redact(result.stderr.splitlines()[-1] if result.stderr.strip() else "No diagnostic available.", [worker_env.get(key, "") for key in MODEL_ENV if "KEY" in key]), file=sys.stderr)
            return 2
        report = json.loads(worker_output.read_text())
    json_path, md_path = write_reports(report, args.output)
    print(f"Atlas {args.mode}: {report['summary']['passed']}/{report['summary']['total']} task contracts passed" + ("; scripted fixture, NOT model performance" if args.mode == "fixture" else "; single live trial per task"))
    print(f"JSON: {json_path}\nMarkdown: {md_path}")
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
