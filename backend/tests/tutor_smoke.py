"""Isolated Tutor API/lifecycle smoke; only external model responses are mocked.

Run: .venv-atlas/bin/python -m backend.tests.tutor_smoke
Never touches the configured business database or reads the developer .env.
"""

import asyncio
import copy
import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

folder = tempfile.TemporaryDirectory(prefix="atlas-tutor-smoke-")
os.environ.update(
    PYTHON_DOTENV_DISABLED="1",
    ATLAS_DATA_DIR=folder.name,
    DATABASE_URL="sqlite:///" + str(Path(folder.name) / "tutor.db"),
    ATLAS_CHECKPOINT_PATH=str(Path(folder.name) / "checkpoint.db"),
    WORKER_MODE="disabled",
    OPENAI_API_KEY="smoke-placeholder-not-a-real-credential",
    OPENAI_BASE_URL="http://127.0.0.1:1/v1",
    OPENAI_MODEL="isolated-smoke-model",
    DEEPSEEK_API_KEY="",
    EMBEDDING_MODEL="",
    TAVILY_API_KEY="",
)

from fastapi.testclient import TestClient
from sqlalchemy import func

from backend.database import SessionLocal
from backend.main import app
from backend.models import (
    Attempt,
    Course,
    Exercise,
    ExerciseMetadata,
    LearningEvidence,
    Memory,
    Node,
    NodeLearningState,
    PlanVersion,
    PracticeBatch,
    TutorEvent,
    TutorTurn,
)
from backend.tutor import paths, store

OPEN_REFERENCE = "在 Python 中，b = a 只建立名字到同一对象的新绑定，不会复制列表；若通过 a 修改该可变对象，b 会观察到同一对象的变化。"
RECOVERY_MEMORY = "租约恢复测试：我偏好通过具体例子学习。"
allow_open_reference = threading.Event()
recovery_waiting = threading.Event()
recovery_model_calls = 0
practice_serial = 0
path_serial = 0
model_contexts = []
CANCEL_GRADE_ANSWER = "SMOKE_CANCEL_GRADE 我把赋值理解为复制列表。"
PRACTICE_FOCUS = "Python 赋值、对象引用与列表可变性"
CANCEL_GENERATION_FOCUS = PRACTICE_FOCUS + "（SMOKE_CANCEL_GENERATION）"
completion_gates = {
    name: {key: threading.Event() for key in ("started", "release", "returned")}
    for name in ("grade", "generation")
}
followup_exercise = {}


async def await_cancellation_boundary(name):
    gate = completion_gates[name]
    gate["started_at"] = time.monotonic()
    gate["started"].set()
    while not gate["release"].is_set():
        await asyncio.sleep(0.002)
    gate["returned_at"] = time.monotonic()
    gate["returned"].set()


def tool_call(identifier, name, arguments):
    return {
        "id": identifier,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


async def external_complete(messages, user_id, step, **kwargs):
    """Deterministic fixtures at the same boundary as a real external completion."""
    global practice_serial, path_serial
    payload = json.loads(messages[-1]["content"])
    if step == "practice_contract_scope":
        ambiguous = payload["request"]["focus"] == "定义与例子"
        return {"context_hash": payload["context_hash"],
            "decision": "uncertain" if ambiguous else "in_scope",
            "interpreted_focus": "未明确的概念" if ambiguous else PRACTICE_FOCUS,
            "reason": "需要明确具体概念。" if ambiguous else "赋值与可变性属于节点范围。",
            "evidence": [] if ambiguous else [{"source_ref": "node_scope",
                "quote": payload["node"]["title"] + "\n" + payload["node"]["objective"]}]}
    if step == "practice_contract_verify":
        source = payload["sources"][0]
        return {"context_hash": payload["context_hash"], "items_hash": payload["items_hash"],
            "items": [{"index": index, "focus": "pass", "answer_key": "pass", "source_support": "pass",
                "reason": "独立检查赋值不会复制列表，名字共享对象；选择题仅此项正确，开放答案覆盖绑定与可变性。",
                "evidence": [{"source_ref": source["source_ref"], "quote": source["text"][:1000]}]}
                for index in range(len(payload["exercises"]))]}
    if step == "adaptive_practice":
        if payload.get("focus") == CANCEL_GENERATION_FOCUS:
            await await_cancellation_boundary("generation")
        practice_serial += 1
        return {
            "exercises": [
                {
                    "type": "choice" if index % 2 == 0 else "open",
                    "prompt": f"Tutor smoke第{practice_serial}批第{index + 1}题：Python 中 b = a 后修改列表为何会被两个名字观察到？",
                    "options": ["两个名字引用同一个列表对象", "赋值会复制列表"]
                    if index % 2 == 0
                    else [],
                    "correct_answer": "两个名字引用同一个列表对象"
                    if index % 2 == 0
                    else OPEN_REFERENCE,
                    "explanation": "赋值只建立绑定，不复制列表；对共享可变对象的修改可被两个名字观察。",
                    "skill_type": "concept",
                }
                for index in range(payload["count"])
            ]
        }
    if step == "rubric_assessment":
        if payload.get("student_answer") == CANCEL_GRADE_ANSWER:
            await await_cancellation_boundary("grade")
        return {
            "criteria_scores": [
                {"id": "correctness", "score": 30},
                {"id": "reasoning", "score": 10},
                {"id": "clarity", "score": 10},
            ],
            "feedback": "回答没有区分名字和对象，需要说明赋值不会复制以及可变对象共享修改。",
            "misconception": "把赋值误当成复制列表，没有理解两个名字共享可变对象。",
        }
    if step == "path_change_preview":
        path_serial += 1
        first = payload["current_path"]["nodes"][0]
        return {
            "title": f"精确确认后的 Atlas 学习路径，第{path_serial}版",
            "nodes": [
                {
                    "key": "retained",
                    "title": first["title"],
                    "summary": first["summary"],
                    "objective": first["objective"],
                    "estimated_minutes": 17,
                    "difficulty": "beginner",
                    "prerequisites": [],
                },
                {
                    "key": "transfer",
                    "title": "补充迁移练习",
                    "summary": "从具体实例迁移到新的情境。",
                    "objective": "根据定义判断新的实例，并解释边界。",
                    "estimated_minutes": 23,
                    "difficulty": "intermediate",
                    "prerequisites": ["retained"],
                },
            ],
        }
    if step == "lesson":
        return "## Python 赋值与对象引用\n赋值不会复制列表，两个名字可以共享同一个可变对象。通过一个名字修改列表，另一个名字会观察到该变化。区分名字绑定与对象本身。"
    raise AssertionError(f"Unexpected external completion: {step}")


async def external_round(config, messages, tools, user_id):
    """Emit native function calls; production runner executes every actual tool."""
    global recovery_model_calls
    encoded = json.dumps(messages, ensure_ascii=False)
    if not allow_open_reference.is_set():
        assert OPEN_REFERENCE not in encoded, "Unsubmitted answer entered Tutor context"
    model_contexts.append(copy.deepcopy(messages))
    last_user = max(
        index for index, message in enumerate(messages) if message["role"] == "user"
    )
    request = messages[last_user]["content"]
    current = messages[last_user + 1 :]
    results = [message for message in current if message["role"] == "tool"]
    calls = None
    output = "Atlas 已完成本次操作。"
    if "SMOKE followup-grade" in request:
        if not results:
            calls = [
                tool_call(
                    "followup-ask",
                    "ask_user",
                    {"question": "请选择这道题的答案：A还是B？"},
                )
            ]
        elif len(results) == 1:
            calls = [
                tool_call(
                    "followup-submit",
                    "submit_answer",
                    {"exercise_id": followup_exercise["id"], "answer": "B"},
                )
            ]
        else:
            output = "已经根据追问后真实提交的答案B完成评分。"
    elif "SMOKE practice-cancel" in request:
        if not results:
            calls = [
                tool_call(
                    "practice-cancel",
                    "generate_practice",
                    {"count": 2, "focus": CANCEL_GENERATION_FOCUS},
                )
            ]
    elif "SMOKE complete-checkpoint" in request:
        raise AssertionError("Complete checkpoint recovery called external model again")
    elif "SMOKE ask" in request:
        if not results:
            calls = [
                tool_call(
                    "ask-1", "ask_user", {"question": "希望先看定义还是先看例子？"}
                )
            ]
        else:
            output = "已收到你的选择：" + json.loads(results[-1]["content"])["answer"]
    elif "SMOKE cancel" in request:
        await asyncio.sleep(20)
        output = "这段迟到的回复不应写入已取消轮次。"
    elif "SMOKE practice" in request:
        if not results:
            calls = [
                tool_call(
                    "practice-1",
                    "generate_practice",
                    {"count": 2, "difficulty": "adaptive", "focus": PRACTICE_FOCUS},
                )
            ]
        else:
            output = "请通过题卡提交真实答案，我会根据具体误解继续讲解。"
    elif "SMOKE path" in request:
        if not results:
            calls = [
                tool_call(
                    "path-1",
                    "propose_path_change",
                    {"reason": "保留基础，增加迁移练习并精确调整时长。"},
                )
            ]
        else:
            output = "已根据你的明确确认结果处理学习路径。"
    elif "SMOKE recovery" in request:
        if not results:
            calls = [
                tool_call(
                    "memory-recover-1",
                    "remember_memory",
                    {"content": RECOVERY_MEMORY, "category": "preference"},
                )
            ]
        else:
            recovery_model_calls += 1
            if recovery_model_calls == 1:
                recovery_waiting.set()
                await asyncio.sleep(20)
            output = "偏好已经保存，恢复执行没有重复新增记忆。"
    elif any(
        "以下是服务器对用户刚提交答案的真实评分" in message.get("content", "")
        for message in current
        if message["role"] == "system"
    ):
        if not results:
            calls = [tool_call("remediate-1", "get_recent_attempts", {})]
        elif len(results) == 1:
            calls = [tool_call("remediate-2", "prepare_lesson", {})]
        else:
            output = "你把赋值当成了复制列表。赋值不会复制对象，两个名字共享列表；请区分名字绑定与对象的修改。"
    elif "SMOKE tools" in request:
        if not results:
            calls = [tool_call("state-1", "get_learning_state", {})]
        else:
            output = "已读取真实课程和学习证据。"
    if calls:
        message = {"role": "assistant", "content": "", "tool_calls": calls}
    else:
        yield {"kind": "text", "text": output}
        message = {"role": "assistant", "content": output}
    yield {"kind": "result", "message": message}


def ok(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def wait_turn(client, identifier, wanted="completed", timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = ok(client.get(f"/api/tutor/turns/{identifier}"))
        if item["status"] == wanted:
            return item
        assert item["status"] not in {"failed", "cancelled"}, item
        time.sleep(0.04)
    raise AssertionError(f"Turn did not reach {wanted}: {item}")


def new_session(client, course_id=None, node_id=None, mode="study"):
    return ok(
        client.post(
            "/api/tutor/sessions",
            json={"course_id": course_id, "node_id": node_id, "mode": mode},
        )
    )


def new_turn(client, session, content, request_id):
    return ok(
        client.post(
            f"/api/tutor/sessions/{session['id']}/turns",
            json={"content": content, "request_id": request_id},
        )
    )


def event_frames(client, identifier, after_seq=0):
    response = client.get(
        f"/api/tutor/turns/{identifier}/events", params={"after_seq": after_seq}
    )
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def snapshot(course_id):
    with SessionLocal() as db:
        return paths.course_snapshot(db, db.get(Course, course_id))


def count(model):
    with SessionLocal() as db:
        return db.query(func.count()).select_from(model).scalar()


def learning_snapshot(node_id):
    """Capture every assessment/practice write that cancellation must roll back."""
    with SessionLocal() as db:
        return {
            "mastery": db.get(Node, node_id).mastery,
            "status": db.get(Node, node_id).status,
            "rows": {
                model.__tablename__: db.query(func.count()).select_from(model).scalar()
                for model in (
                    Attempt,
                    LearningEvidence,
                    Exercise,
                    ExerciseMetadata,
                    PracticeBatch,
                    NodeLearningState,
                    Memory,
                )
            },
        }


def finish_cancelled_completion(client, turn_id, gate_name):
    """Release immediately after cancel, before the two-second lease watchdog."""
    gate = completion_gates[gate_name]
    assert gate["started"].wait(8), f"{gate_name} did not reach external await"
    started = time.monotonic()
    assert (
        ok(client.post(f"/api/tutor/turns/{turn_id}/cancel"))["status"] == "cancelled"
    )
    gate["release"].set()
    assert gate["returned"].wait(0.5), (
        "Model did not promptly return after cancellation"
    )
    # The continuation performs synchronous DB validation/flush/commit in the same
    # event-loop tick. A short yield lets its commit fence reject the stale owner.
    time.sleep(0.08)
    assert time.monotonic() - started < 1.5, (
        "Boundary check missed the pre-watchdog window"
    )
    turn = ok(client.get(f"/api/tutor/turns/{turn_id}"))
    assert turn["status"] == "cancelled"
    assert not any(
        event["type"] in {"assessment", "question"} for event in turn["events"]
    )


def run():
    restart_turn = None
    persisted_frames = None
    cookies = None
    with (
        patch("backend.tutor.runner.model_round", external_round),
        patch("backend.learning.complete", external_complete),
        patch("backend.practice_contracts.complete", external_complete),
        patch("backend.tutor.paths.complete", external_complete),
    ):
        with TestClient(app) as owner:
            other, anonymous = TestClient(app), TestClient(app)
            try:
                ok(anonymous.get("/api/tutor/sessions"), 401)
                for client, name in ((owner, "owner"), (other, "other")):
                    response = client.post(
                        "/api/auth/register",
                        json={
                            "email": name + "@tutor-smoke.test",
                            "password": "AtlasSmoke123!",
                            "full_name": name,
                        },
                    )
                    ok(response)
                    assert "HttpOnly" in response.headers["set-cookie"]
                template = ok(owner.get("/api/templates"))[0]
                course = ok(owner.post(f"/api/templates/{template['id']}/enroll"))
                course_id, node_id = course["id"], course["nodes"][0]["id"]
                session = new_session(owner, course_id, node_id)
                ok(other.get(f"/api/tutor/sessions/{session['id']}"), 404)
                ok(
                    other.post(
                        "/api/tutor/sessions",
                        json={"course_id": course_id, "node_id": node_id},
                    ),
                    404,
                )
                assert ok(other.get("/api/tutor/sessions")) == []
                assert session["id"] in [
                    item["id"]
                    for item in ok(
                        owner.get(
                            "/api/tutor/sessions", params={"course_id": course_id}
                        )
                    )
                ]

                # Native tools, admission idempotency and persisted SSE replay.
                turn = new_turn(owner, session, "SMOKE tools 读取真实状态", "tools")
                replay = new_turn(owner, session, "SMOKE tools 读取真实状态", "tools")
                assert replay["id"] == turn["id"]
                ok(
                    owner.post(
                        f"/api/tutor/sessions/{session['id']}/turns",
                        json={"content": "不同内容", "request_id": "tools"},
                    ),
                    409,
                )
                done = wait_turn(owner, turn["id"])
                frames = event_frames(owner, turn["id"])
                assert [frame["seq"] for frame in frames] == list(
                    range(1, done["last_seq"] + 1)
                )
                assert {"tool_start", "tool_result", "content", "done"} <= {
                    frame["type"] for frame in frames
                }
                state_result = next(
                    frame["payload"]["result"]
                    for frame in frames
                    if frame["type"] == "tool_result"
                )
                assert state_result["course"]["id"] == course_id
                assert event_frames(owner, turn["id"], frames[2]["seq"]) == frames[3:]
                ok(other.get(f"/api/tutor/turns/{turn['id']}"), 404)
                ok(other.get(f"/api/tutor/turns/{turn['id']}/events"), 404)

                # Pause, one active turn, resume, and cancellation of live work.
                asked = new_turn(owner, session, "SMOKE ask 学习偏好", "ask")
                waiting = wait_turn(owner, asked["id"], "waiting_input")
                assert waiting["pending_action"]["question"]
                ok(
                    owner.post(
                        f"/api/tutor/sessions/{session['id']}/turns",
                        json={"content": "不能并行入队", "request_id": "blocked"},
                    ),
                    409,
                )
                ok(
                    other.post(
                        f"/api/tutor/turns/{asked['id']}/respond",
                        json={"content": "入侵"},
                    ),
                    404,
                )
                ok(
                    owner.post(
                        f"/api/tutor/turns/{asked['id']}/respond",
                        json={"content": "先看例子"},
                    )
                )
                assert "先看例子" in wait_turn(owner, asked["id"])["output"]
                cancelled = new_turn(owner, session, "SMOKE cancel 慢速模型", "cancel")
                wait_turn(owner, cancelled["id"], "running")
                ok(other.post(f"/api/tutor/turns/{cancelled['id']}/cancel"), 404)
                assert (
                    ok(owner.post(f"/api/tutor/turns/{cancelled['id']}/cancel"))[
                        "status"
                    ]
                    == "cancelled"
                )
                assert (
                    ok(owner.post(f"/api/tutor/turns/{cancelled['id']}/cancel"))[
                        "status"
                    ]
                    == "cancelled"
                )

                # Question -> real API answer -> evidence, error memory and remediation.
                practice = new_turn(
                    owner, session, "SMOKE practice " + PRACTICE_FOCUS, "practice"
                )
                practice = wait_turn(owner, practice["id"])
                question = next(
                    event["payload"]
                    for event in practice["events"]
                    if event["type"] == "question"
                )
                assert len(question["exercises"]) == 2
                assert OPEN_REFERENCE not in json.dumps(question, ensure_ascii=False)
                assert all(
                    "correct_answer" not in exercise and "explanation" not in exercise
                    for exercise in question["exercises"]
                )
                choice, opened = question["exercises"]
                before_attempts, before_evidence = (
                    count(Attempt),
                    count(LearningEvidence),
                )
                answer_body = {
                    "exercise_id": choice["id"],
                    "answer": "B",
                    "request_id": "answer-choice",
                }
                ok(
                    other.post(
                        f"/api/tutor/sessions/{session['id']}/answers", json=answer_body
                    ),
                    404,
                )
                graded = ok(
                    owner.post(
                        f"/api/tutor/sessions/{session['id']}/answers", json=answer_body
                    )
                )
                assert (
                    ok(
                        owner.post(
                            f"/api/tutor/sessions/{session['id']}/answers",
                            json=answer_body,
                        )
                    )["id"]
                    == graded["id"]
                )
                wrong = wait_turn(owner, graded["id"])
                assessment = next(
                    event["payload"]
                    for event in wrong["events"]
                    if event["type"] == "assessment"
                )
                assert assessment["score"] == 0 and assessment["independent"]
                assert "不会复制" in wrong["output"]
                assert (
                    count(Attempt) == before_attempts + 1
                    and count(LearningEvidence) == before_evidence + 1
                )
                with SessionLocal() as db:
                    memory = db.query(Memory).filter_by(category="misconception").one()
                    assert (
                        "赋值会复制列表" in memory.content
                        and "纠正" in memory.content
                    )
                bad_replay = {**answer_body, "answer": "A"}
                ok(
                    owner.post(
                        f"/api/tutor/sessions/{session['id']}/answers", json=bad_replay
                    ),
                    409,
                )
                allow_open_reference.set()
                open_turn = ok(
                    owner.post(
                        f"/api/tutor/sessions/{session['id']}/answers",
                        json={
                            "exercise_id": opened["id"],
                            "answer": "我把赋值理解为复制列表。",
                            "request_id": "answer-open",
                        },
                    )
                )
                open_turn = wait_turn(owner, open_turn["id"])
                rubric = next(
                    event["payload"]
                    for event in open_turn["events"]
                    if event["type"] == "assessment"
                )
                assert (
                    rubric["score"] == 50
                    and len(rubric["criteria_scores"]) == 3
                    and rubric["mastery"] < 80
                )
                assert "共享" in rubric["misconception"]
                assert ok(owner.get("/api/review/due"))

                # Cancel while an open-answer model is awaiting, then return its
                # score immediately. The service commit must reject cancellation
                # without relying on the two-second lease watchdog.
                cancel_grade_session = new_session(owner, course_id, node_id)
                before_cancel_grade = learning_snapshot(node_id)
                cancel_grade = ok(
                    owner.post(
                        f"/api/tutor/sessions/{cancel_grade_session['id']}/answers",
                        json={
                            "exercise_id": opened["id"],
                            "answer": CANCEL_GRADE_ANSWER,
                            "request_id": "cancel-grade-boundary",
                        },
                    )
                )
                finish_cancelled_completion(owner, cancel_grade["id"], "grade")
                assert learning_snapshot(node_id) == before_cancel_grade

                # Apply the same pre-watchdog race to a tool-generated batch.
                cancel_practice_session = new_session(owner, course_id, node_id)
                before_cancel_practice = learning_snapshot(node_id)
                cancel_practice = new_turn(
                    owner,
                    cancel_practice_session,
                    "SMOKE practice-cancel 取消模型生成中的补题",
                    "cancel-generation-boundary",
                )
                finish_cancelled_completion(owner, cancel_practice["id"], "generation")
                assert learning_snapshot(node_id) == before_cancel_practice

                # The original input contains no answer. A real persisted respond
                # event supplies B, which submit_answer must accept as its source.
                followup_exercise["id"] = choice["id"]
                followup_session = new_session(owner, course_id, node_id)
                followup_input = "SMOKE followup-grade 请先追问，再根据我的回答评分。"
                assert "b" not in followup_input.lower()
                followup = new_turn(
                    owner, followup_session, followup_input, "followup-answer"
                )
                wait_turn(owner, followup["id"], "waiting_input")
                attempts_before_followup = count(Attempt)
                ok(
                    owner.post(
                        f"/api/tutor/turns/{followup['id']}/respond",
                        json={"content": "B"},
                    )
                )
                followed = wait_turn(owner, followup["id"])
                followed_assessment = next(
                    event["payload"]
                    for event in followed["events"]
                    if event["type"] == "assessment"
                )
                assert (
                    followed_assessment["answer"] == "B"
                    and followed_assessment["score"] == 0
                )
                assert count(Attempt) == attempts_before_followup + 1
                assert any(
                    event["type"] == "user_response"
                    and event["payload"]["content"] == "B"
                    for event in followed["events"]
                )

                # Exact path preview: no mutation before confirmation or on rejection.
                outline = new_session(owner, course_id, node_id, "outline")
                before = snapshot(course_id)
                proposed = new_turn(
                    owner, outline, "SMOKE path 拒绝这一版", "path-reject"
                )
                proposed = wait_turn(owner, proposed["id"], "waiting_confirmation")
                assert (
                    proposed["pending_action"]["changes"]
                    and snapshot(course_id) == before
                )
                ok(
                    owner.post(
                        f"/api/tutor/turns/{proposed['id']}/respond",
                        json={
                            "approved": False,
                            "action_id": proposed["pending_action"]["action_id"],
                        },
                    )
                )
                wait_turn(owner, proposed["id"])
                assert snapshot(course_id) == before
                accepted = new_turn(
                    owner, outline, "SMOKE path 接受精确预览", "path-accept"
                )
                accepted = wait_turn(owner, accepted["id"], "waiting_confirmation")
                with SessionLocal() as db:
                    private_plan = copy.deepcopy(
                        db.get(TutorTurn, accepted["id"]).pending_action["plan"]
                    )
                assert snapshot(course_id) == before
                versions = count(PlanVersion)
                ok(
                    owner.post(
                        f"/api/tutor/turns/{accepted['id']}/respond",
                        json={
                            "approved": True,
                            "action_id": accepted["pending_action"]["action_id"],
                        },
                    )
                )
                wait_turn(owner, accepted["id"])
                after = snapshot(course_id)
                assert (
                    after["title"] == private_plan["title"]
                    and after["version"] == before["version"] + 1
                )
                for actual, expected in zip(
                    after["nodes"], private_plan["nodes"], strict=True
                ):
                    assert all(
                        actual[key] == expected[key]
                        for key in (
                            "id",
                            "title",
                            "objective",
                            "summary",
                            "estimated_minutes",
                            "difficulty",
                            "prerequisites",
                        )
                    )
                assert count(PlanVersion) == versions + 1
                stale = new_turn(
                    owner, outline, "SMOKE path 制造过期预览", "path-stale"
                )
                stale = wait_turn(owner, stale["id"], "waiting_confirmation")
                ok(
                    owner.patch(
                        f"/api/nodes/{node_id}",
                        json={"title": "预览之后用户手动编辑的节点"},
                    )
                )
                changed = snapshot(course_id)
                response = owner.post(
                    f"/api/tutor/turns/{stale['id']}/respond",
                    json={
                        "approved": True,
                        "action_id": stale["pending_action"]["action_id"],
                    },
                )
                ok(response, 409)
                assert snapshot(course_id) == changed
                ok(
                    owner.post(
                        f"/api/tutor/turns/{stale['id']}/respond",
                        json={
                            "approved": False,
                            "action_id": stale["pending_action"]["action_id"],
                        },
                    )
                )
                wait_turn(owner, stale["id"])

                # Simulate loss after the side effect commits but before its tool
                # checkpoint advances. The real worker reclaims and re-executes.
                recovery = new_session(owner, course_id, node_id)
                recovering = new_turn(
                    owner, recovery, f"SMOKE recovery 保存我的学习偏好：{RECOVERY_MEMORY}", "recover"
                )
                assert recovery_waiting.wait(8), (
                    "Recovery fixture never reached post-tool model round"
                )
                with SessionLocal() as db:
                    row = db.get(TutorTurn, recovering["id"])
                    cp = copy.deepcopy(row.checkpoint)
                    call_message = next(
                        message
                        for message in reversed(cp["messages"])
                        if message.get("tool_calls")
                    )
                    cp["messages"] = cp["messages"][:-1]
                    cp.update(
                        stage="tools",
                        tool_index=0,
                        pending_calls=call_message["tool_calls"],
                    )
                    row.checkpoint, row.worker_token = cp, "simulated-expired-owner"
                    row.lease_until = (
                        datetime.now(UTC) - timedelta(minutes=1)
                    ).isoformat()
                    row.status = "running"
                    db.commit()
                    assert (
                        db.query(Memory).filter_by(content=RECOVERY_MEMORY).count() == 1
                    )
                recovered = wait_turn(owner, recovering["id"])
                with SessionLocal() as db:
                    assert (
                        db.query(Memory).filter_by(content=RECOVERY_MEMORY).count() == 1
                    )
                    event_count = (
                        db.query(TutorEvent).filter_by(turn_id=recovering["id"]).count()
                    )
                    assert event_count == recovered["last_seq"]
                assert recovery_model_calls >= 2 and "恢复执行" in recovered["output"]
                assert (
                    ok(owner.get(f"/api/tutor/turns/{cancelled['id']}"))["status"]
                    == "cancelled"
                )
                # A completed provider checkpoint can outlive a killed worker
                # before finish(). Reclaim it without re-entering model_round or
                # appending its already durable output a second time.
                complete_session = new_session(owner, course_id, node_id)
                saved_output = "完整的已保存回复，只出现一次。"
                model_calls_before_complete = len(model_contexts)
                with SessionLocal() as db:
                    user_id = db.get(TutorTurn, recovered["id"]).user_id
                    completed_checkpoint = TutorTurn(
                        user_id=user_id,
                        session_id=complete_session["id"],
                        request_id="complete-checkpoint-recovery",
                        input="SMOKE complete-checkpoint 已完成模型轮次",
                        output=saved_output,
                        status="running",
                        worker_token="expired-complete-checkpoint-owner",
                        lease_until=(
                            datetime.now(UTC) - timedelta(minutes=1)
                        ).isoformat(),
                        checkpoint={
                            "stage": "complete",
                            "rounds": 1,
                            "stable_output": saved_output,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "SMOKE complete-checkpoint",
                                },
                                {"role": "assistant", "content": saved_output},
                            ],
                        },
                    )
                    db.add(completed_checkpoint)
                    db.flush()
                    store.add_event(
                        db, completed_checkpoint, "content", {"text": saved_output}
                    )
                    db.commit()
                    complete_id = completed_checkpoint.id
                completed_recovery = wait_turn(owner, complete_id)
                complete_frames = event_frames(owner, complete_id)
                assert len(model_contexts) == model_calls_before_complete
                assert completed_recovery["output"] == saved_output
                assert [
                    frame["payload"]["text"]
                    for frame in complete_frames
                    if frame["type"] == "content"
                ] == [saved_output]
                assert sum(frame["type"] == "done" for frame in complete_frames) == 1

                restart_turn, persisted_frames = (
                    recovered["id"],
                    event_frames(owner, recovered["id"]),
                )
                cookies = dict(owner.cookies)
                assert all(
                    frame["seq"] == index + 1
                    for index, frame in enumerate(persisted_frames)
                )
            finally:
                other.close()
                anonymous.close()
        # Full lifespan restart proves events/session history survive worker shutdown.
        with TestClient(app) as restarted:
            restarted.cookies.update(cookies)
            assert (
                ok(restarted.get(f"/api/tutor/turns/{restart_turn}"))["status"]
                == "completed"
            )
            assert event_frames(restarted, restart_turn) == persisted_frames
            assert model_contexts
    print(
        "PASS: Tutor auth/isolation, native tools, admission replay, one active turn, durable SSE, ask/resume, cancel, question/answer/evidence/remediation, exact path confirmation/rejection/staleness, lease recovery deduplication, cancellation commit fencing, resumed-answer provenance, complete-checkpoint recovery, lifecycle restart"
    )


if __name__ == "__main__":
    run()
