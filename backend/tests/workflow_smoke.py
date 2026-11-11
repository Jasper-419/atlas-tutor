"""Focused workflow recovery/contract check with an explicit test-only model stub.

This verifies persistence and API contracts; it does not claim real model success.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

folder = tempfile.TemporaryDirectory(prefix="atlas-workflow-smoke-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(folder.name) / "atlas.db")
os.environ["ATLAS_CHECKPOINT_PATH"] = str(Path(folder.name) / "checkpoints.db")
os.environ["WORKER_MODE"] = "disabled"
os.environ["OPENAI_API_KEY"] = "explicit-test-only-key"
from fastapi.testclient import TestClient
from backend.main import app
from backend.workflows import claim_task, run_task, check_live, Cancelled
from backend.database import SessionLocal
from backend.models import Task, now

PLAN = {
    "title": "Workflow test plan",
    "nodes": [
        {
            "key": "a",
            "title": "State",
            "summary": "State values",
            "objective": "Explain state",
            "estimated_minutes": 20,
            "difficulty": "beginner",
            "prerequisites": [],
        },
        {
            "key": "b",
            "title": "Recovery",
            "summary": "Recover execution",
            "objective": "Use persistence",
            "estimated_minutes": 20,
            "difficulty": "beginner",
            "prerequisites": ["a"],
        },
    ],
}


async def interrupt_worker(task_id):
    entered = asyncio.Event()

    async def wait_for_shutdown(*args, **kwargs):
        entered.set()
        await asyncio.Future()

    with patch("backend.workflows.complete", new=wait_for_shutdown):
        running = asyncio.create_task(run_task(task_id))
        await entered.wait()
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass


async def stream(*args, **kwargs):
    yield "A state "
    yield "holds values."


async def research_model(messages, user_id, step, task_id=None, json_mode=False):
    """Explicit stage-shaped fixtures; this test never calls a real model."""
    if step == "research_outline":
        return {"topics": [{"title": "LangGraph state", "query": "LangGraph state persistence"}]}
    if step == "research_coverage":
        return {"topics": [{"index": 0, "sufficient": True, "gap": "", "followup_query": ""}]}
    if step == "research_report":
        return {"summary": "State passes between graph nodes; checkpoints persist it. [S1]",
                "sections": [{"finding": "Checkpoints persist state.", "source_refs": ["S1"]}]}
    raise AssertionError("unexpected research model stage: " + step)


def run():
    with TestClient(app) as client:
        client.post(
            "/api/auth/register",
            json={
                "email": "workflow@example.com",
                "password": "Workflow123!",
                "full_name": "Workflow",
            },
        )
        course = client.post(
            "/api/courses",
            json={
                "goal": "LangGraph fundamentals",
                "background": "Python",
                "minutes_per_day": 20,
            },
        ).json()
        task_id = claim_task(course["task_id"])
        doc = (
            "https://example.com/reference",
            "Explicit test reference",
            "State is a value passed between graph nodes. Checkpoints persist that state.",
        )
        with (
            patch("backend.research.safe_fetch", new=AsyncMock(return_value=doc)),
            patch("backend.research.complete", new=research_model),
            patch("backend.research.get_settings") as settings,
        ):
            settings.return_value.tavily_key = ""
            asyncio.run(interrupt_worker(task_id))
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            assert task.status == "running"
            old_worker = task.worker_token
            task.lease_until = "2000-01-01T00:00:00+00:00"
            db.commit()
        assert claim_task(task_id) == task_id
        with SessionLocal() as db:
            assert db.get(Task, task_id).worker_token != old_worker
        with (
            patch(
                "backend.research.safe_fetch",
                new=AsyncMock(
                    side_effect=AssertionError("completed research was repeated")
                ),
            ),
            patch("backend.workflows.complete", new=AsyncMock(return_value=PLAN)),
        ):
            asyncio.run(run_task(task_id))
        task = client.get("/api/tasks/" + task_id).json()
        assert task["status"] == "succeeded", task
        detail = client.get("/api/courses/" + course["id"]).json()
        assert (
            detail["total_nodes"] == 2
            and len(detail["sources"]) == 1
            and len(detail["edges"]) == 1
        )
        assert detail["nodes"][1]["status"] == "locked"
        node = detail["nodes"][0]
        with patch("backend.main.stream_chat", new=stream):
            response = client.post(
                "/api/nodes/" + node["id"] + "/messages",
                json={"content": "换个例子讲解这一节", "request_id": "stream-test"},
            )
        assert "event: done" in response.text and "event: error" not in response.text, (
            response.text
        )
        replay = client.post(
            "/api/nodes/" + node["id"] + "/messages",
            json={"content": "换个例子讲解这一节", "request_id": "stream-test"},
        )
        assert "event: done" in replay.text
        saved_messages = client.get("/api/nodes/" + node["id"] + "/messages").json()
        assert len(saved_messages) == 2
        assert saved_messages[-1]["citations"], "隐式追问必须使用当前知识节点检索资料"
        legacy_replan = client.post(
            "/api/courses/" + course["id"] + "/replan", json={"reason": "More practice"}
        )
        assert legacy_replan.status_code == 409, "Existing paths require a precise confirmed preview"
        # Tutor smoke covers exact path approval. Exercise the shared task
        # cancellation/retry fence with an independently authorized research job.
        retry_job = client.post(
            "/api/courses/" + course["id"] + "/research", json={"query": "More practice with LangGraph persistence"}
        ).json()
        claim_task(retry_job["id"])
        with SessionLocal() as db:
            old_run = db.get(Task, retry_job["id"]).run_id
        client.post("/api/tasks/" + retry_job["id"] + "/cancel")
        client.post("/api/tasks/" + retry_job["id"] + "/retry")
        claim_task(retry_job["id"])
        try:
            check_live(retry_job["id"], old_run)
        except Cancelled:
            pass
        else:
            raise AssertionError("stale cancelled run accepted")
    print(
        "PASS: graph checkpoint resume, source persistence, lease fencing, DAG contract, SSE persistence/replay, cancelled-run fencing (explicit test-only model stub)"
    )


if __name__ == "__main__":
    run()
