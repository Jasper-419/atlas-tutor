"""Isolated API/Loop/real Python checks; only model responses/usage are fixtures."""
import json
import os
from pathlib import Path
import tempfile
import asyncio
import threading
import time
from unittest.mock import patch

folder = Path(tempfile.mkdtemp(prefix="atlas-verified-agent-"))
os.environ.update(ATLAS_DATA_DIR=str(folder), DATABASE_URL="sqlite:///" + str(folder / "atlas.db"),
                 ATLAS_CHECKPOINT_PATH=str(folder / "checkpoint.db"), CHECKPOINT_DATABASE_URL="",
                 OPENAI_API_KEY="fixture-only", OPENAI_BASE_URL="http://127.0.0.1:1/v1", OPENAI_MODEL="fixture-model")


def tool(identifier, name, arguments):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class Provider:
    calls = 0

    async def round(self, config, messages, tools, user_id):
        request = next(item["content"] for item in reversed(messages) if item["role"] == "user")
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        calls, text = [], "执行得到55，检查通过；这只证明列出的检查。"
        if request == "qa-denied":
            if not results:
                calls = [tool("denied", "python_check", {"step_id": "s1", "code": "x=55", "checks": [{"expression": "x", "expected": 55}]})]
        elif request == "nested-cancel":
            calls = [tool("cancel-nested-plan", "solve_plan", {"goal": "等待内部模型", "steps": [{"id": "s1", "title": "等待补充", "method": "reasoning"}]})]
        else:
            self.calls += 1
            if self.calls == 1:
                text = "虚构的提前成功声明，必须被生命周期校验撤回。"
            elif not results:
                calls = [tool("plan", "solve_plan", {"goal": "求和并核对", "steps": [{"id": "s1", "title": "计算1到10的和", "method": "python"}]})]
            elif len(results) == 1:
                calls = [tool("wrong", "python_check", {"step_id": "s1", "code": "x=54", "checks": [{"expression": "x", "expected": 55}]})]
            elif len(results) == 2:
                calls = [tool("invalid-proof", "solve_finish_step", {"step_id": "s1", "explanation": "尝试使用失败凭据", "evidence_id": results[-1]["execution"]["evidence_id"]})]
            elif len(results) == 3:
                calls = [tool("fixed", "python_check", {"step_id": "s1", "code": "x=sum(range(11))\nprint(x)", "checks": [{"expression": "x", "expected": 55}]})]
            elif len(results) == 4:
                calls = [tool("finish-step", "solve_finish_step", {"step_id": "s1", "explanation": "实际运行求和并检查55", "evidence_id": results[-1]["execution"]["evidence_id"]})]
            elif len(results) == 5:
                calls = [tool("finish", "solve_finish", {"summary": "实际执行结果为55，检查通过。"})]
        if calls:
            result = {"role": "assistant", "content": "", "tool_calls": calls}
        else:
            yield {"kind": "text", "text": text}
            result = {"role": "assistant", "content": text}
        yield {"kind": "result", "message": result, "usage": {"prompt_tokens": 100, "completion_tokens": 10}, "usage_known": True}


def main():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.llm import record_trace
    from backend.llm import complete
    from backend.tutor.tools import execute
    from backend.database import SessionLocal
    from backend.models.tutor import TutorTurn
    from backend.models import User, Exercise

    nested_started = threading.Event()
    async def pending_provider(*args, **kwargs):
        nested_started.set()
        await asyncio.sleep(60)

    async def dispatch(context, call):
        if call["id"] == "cancel-nested-plan":
            await complete([{"role": "user", "content": "isolated cancellation probe"}], context.user_id, "fixture_pending_model")
        if call["function"]["name"] == "solve_plan":
            # Artificial provider measurement, explicitly a telemetry fixture.
            record_trace(context.user_id, "fixture_nested_model", model="fixture-model", duration_ms=7, prompt_tokens=30, completion_tokens=3)
        return await execute(context, call)

    def ok(response):
        assert response.status_code == 200, response.text
        return response.json()

    def wait(client, identifier):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = ok(client.get(f"/api/tutor/turns/{identifier}"))
            if value["status"] in {"completed", "failed", "cancelled"}:
                return value
            time.sleep(.05)
        raise AssertionError("Turn did not finish")

    provider = Provider()
    with patch("backend.tutor.runner.model_round", provider.round), patch("backend.tutor.runner.execute", dispatch), TestClient(app) as client:
        ok(client.post("/api/auth/register", json={"email": "verified@atlas.test", "password": "AtlasTest123!", "full_name": "Verified fixture"}))
        session = ok(client.post("/api/tutor/sessions", json={}))
        endpoint = f"/api/tutor/sessions/{session['id']}/turns"
        assert client.post(endpoint, json={"content": "test", "request_id": "conflict", "profile": "qa", "capability": "solve"}).status_code == 422
        body = {"content": "计算1到10的和并用执行结果核对", "request_id": "solve", "capability": "solve"}
        turn = ok(client.post(endpoint, json=body))
        completed = wait(client, turn["id"])
        assert completed["status"] == "completed", completed
        assert completed["result"]["outcome"] == "verified" and completed["result"]["verified_steps"] == 1
        assert "虚构" not in completed["output"]
        results = [event["payload"]["result"] for event in completed["events"] if event["type"] == "tool_result"]
        assert results[1]["execution"]["status"] == "failed" and results[2].get("error")
        assert results[3]["execution"]["stdout"].strip() == "55"
        assert ok(client.post(endpoint, json=body))["id"] == turn["id"]
        assert client.post(endpoint, json={**body, "capability": "tutor"}).status_code == 409
        detail = ok(client.get(f"/api/agent/runs/agent/{turn['id']}"))
        nested = [span for span in detail["spans"] if span.get("parent_id")]
        assert len(nested) == 1 and nested[0]["parent_id"] == "tool:plan"
        usage = detail["usage"]
        assert usage["internal_model_calls"] == 1 and usage["model_calls"] == usage["main_model_calls"] + 1
        assert usage["prompt_tokens"] == usage["main_model_calls"] * 100 + 30
        assert detail["run"]["duration_ms"] == sum(span["duration_ms"] for span in detail["spans"] if span["kind"] in {"model", "tool"} and not span.get("parent_id"))
        exported = ok(client.get(f"/api/agent/runs/agent/{turn['id']}/export"))
        assert "x=sum" not in json.dumps(exported) and "checkpoint" not in exported
        with SessionLocal() as db:
            snapshot = db.get(TutorTurn, turn["id"]).checkpoint
            assert snapshot["solve"]["steps"][0]["status"] == "verified"
        qa = ok(client.post("/api/tutor/sessions", json={}))
        denied = ok(client.post(f"/api/tutor/sessions/{qa['id']}/turns", json={"content": "qa-denied", "request_id": "qa", "capability": "qa"}))
        denied = wait(client, denied["id"])
        assert any(event["type"] == "tool_result" and event["payload"]["result"].get("error") for event in denied["events"])
        template = ok(client.get("/api/templates"))[0]
        course = ok(client.post(f"/api/templates/{template['id']}/enroll"))
        waiting_session = ok(client.post("/api/tutor/sessions", json={"course_id": course["id"]}))
        with SessionLocal() as db:
            user_id = db.query(User.id).filter_by(email="verified@atlas.test").scalar()
            node_id = course["nodes"][0]["id"]
            exercise = Exercise(user_id=user_id, node_id=node_id, type="choice", prompt="隔离接口边界检查", options=["A", "B"], correct_answer="A")
            db.add(exercise)
            waiting = TutorTurn(user_id=user_id, session_id=waiting_session["id"], request_id="waiting", input="尚未完成的解题", status="waiting_input", pending_action={"kind": "ask_user", "action_id": "pending", "question": "请补充条件"}, checkpoint={"agent": {"capability": "solve", "profile": "solve"}, "solve": {"status": "active"}})
            db.add(waiting); db.commit()
            exercise_id, waiting_id = exercise.id, waiting.id
        response = client.post(f"/api/tutor/sessions/{waiting_session['id']}/answers", json={"exercise_id": exercise_id, "answer": "A", "request_id": "cannot-close-solve"})
        assert response.status_code == 409
        assert ok(client.get(f"/api/tutor/turns/{waiting_id}"))["status"] == "waiting_input"
        cancel_session = ok(client.post("/api/tutor/sessions", json={}))
        with patch("backend.llm.request_completion", pending_provider):
            pending = ok(client.post(f"/api/tutor/sessions/{cancel_session['id']}/turns", json={"content": "nested-cancel", "request_id": "cancel", "capability": "solve"}))
            assert nested_started.wait(10), "Nested provider did not begin"
            ok(client.post(f"/api/tutor/turns/{pending['id']}/cancel"))
            detail = ok(client.get(f"/api/agent/runs/agent/{pending['id']}"))
            internal = [span for span in detail["spans"] if (span.get("metadata") or {}).get("scope") == "internal"]
            assert len(internal) == 1 and internal[0]["status"] == "cancelled"
            assert detail["usage"]["internal_model_calls"] == 1 and detail["usage"]["prompt_tokens"] is None
    print("PASS: real API/worker/Python failure→repair→evidence→finish; premature completion blocked; policy/replay; nested usage/time; sanitized export; qa denial (model/usage fixture)")


if __name__ == "__main__":
    main()
