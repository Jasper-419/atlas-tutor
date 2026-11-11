"""One focused end-to-end backend check; run with the Atlas virtualenv."""

import os
import tempfile
from pathlib import Path

folder = tempfile.TemporaryDirectory(prefix="atlas-smoke-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(folder.name) / "test.db")
os.environ["ATLAS_CHECKPOINT_PATH"] = str(Path(folder.name) / "checkpoint.db")
os.environ["WORKER_MODE"] = "disabled"
from fastapi.testclient import TestClient
from backend.main import app


def run():
    with TestClient(app) as a, TestClient(app) as b:
        response = a.post(
            "/api/auth/register",
            json={
                "email": "a@example.com",
                "password": "AtlasSmoke123!",
                "full_name": "A",
            },
        )
        assert response.status_code == 200, response.text
        assert "HttpOnly" in response.headers["set-cookie"]
        assert (
            b.post(
                "/api/auth/register",
                json={
                    "email": "b@example.com",
                    "password": "AtlasSmoke123!",
                    "full_name": "B",
                },
            ).status_code
            == 200
        )
        templates = a.get("/api/templates").json()
        course = a.post(f"/api/templates/{templates[0]['id']}/enroll").json()
        assert course["status"] == "active", course
        cid, node = course["id"], course["nodes"][0]
        assert b.get(f"/api/courses/{cid}").status_code == 404
        assert b.get(f"/api/nodes/{node['id']}").status_code == 404
        assert a.post(f"/api/nodes/{node['id']}/lesson").json()["content"]
        exercises = a.get(f"/api/nodes/{node['id']}/exercises").json()
        assert exercises and "correct_answer" not in exercises[0]
        exercise = exercises[0]
        first = a.post(
            f"/api/exercises/{exercise['id']}/attempts",
            json={"answer": exercise["options"][0], "request_id": "smoke-answer"},
        )
        assert first.status_code == 200, first.text
        replay = a.post(
            f"/api/exercises/{exercise['id']}/attempts",
            json={"answer": exercise["options"][0], "request_id": "smoke-answer"},
        )
        assert first.json()["id"] == replay.json()["id"]
        assert a.get("/api/analytics").json()["stats"]["attempts"] == 1
        # A correct choice must not bypass an unanswered open exercise.
        from backend.database import SessionLocal
        from backend.models import Exercise, Node

        with SessionLocal() as db:
            open_question = Exercise(
                user_id=a.get("/api/me").json()["id"],
                node_id=node["id"],
                type="open",
                prompt="Explain the idea",
                options=[],
                rubric="Explain clearly",
                correct_answer="A clear explanation",
                explanation="Explain clearly",
            )
            db.add(open_question)
            db.commit()
        partial = a.post(
            f"/api/exercises/{exercise['id']}/attempts",
            json={"answer": exercise["options"][0], "request_id": "partial-coverage"},
        ).json()
        assert partial["mastery"] < 80, "An unanswered exercise must prevent mastery"
        assert a.get(f"/api/courses/{cid}").json()["nodes"][1]["status"] == "locked"
        source = a.post(
            f"/api/courses/{cid}/sources/text",
            json={
                "title": "Smoke reference",
                "content": "Checkpoint persists graph state. Recovery uses a thread identifier.",
            },
        ).json()
        assert source["chunk_count"] == 1, source
        assert a.get(f"/api/courses/{cid}/search", params={"q": "Checkpoint"}).json()
        assert b.delete(f"/api/sources/{source['id']}").status_code == 404
        memory = a.post(
            "/api/me/memories",
            json={
                "content": "Prefer short code samples",
                "category": "preference",
                "course_id": cid,
            },
        ).json()
        assert (
            b.patch(
                f"/api/me/memories/{memory['id']}", json={"content": "No"}
            ).status_code
            == 404
        )
        assert a.get("/api/me/export").status_code == 200
        assert "correct_answer" not in a.get("/api/me/export").json()["exercises"][0]
        assert (
            b.patch(f"/api/nodes/{node['id']}", json={"title": "Intrusion"}).status_code
            == 404
        )
        changed = a.patch(
            f"/api/nodes/{node['id']}", json={"title": "State fundamentals"}
        ).json()
        assert changed["title"] == "State fundamentals"
        second = course["nodes"][1]
        assert (
            a.put(
                f"/api/courses/{cid}/graph",
                json={
                    "edges": [
                        {"source": node["id"], "target": second["id"]},
                        {"source": second["id"], "target": node["id"]},
                    ]
                },
            ).status_code
            == 422
        )
        assert (
            a.put(
                f"/api/courses/{cid}/graph",
                json={"edges": [{"source": "other-user-node", "target": node["id"]}]},
            ).status_code
            == 422
        )
        assert (
            a.put(f"/api/courses/{cid}/graph", json={"edges": course["edges"]}).json()[
                "plan_version"
            ]
            == 2
        )
        # Saved lesson references must be returned when opening the course again.
        with SessionLocal() as db:
            stored = db.get(Node, node["id"])
            stored.lesson_citations = [
                {
                    "id": "saved-citation",
                    "source_id": source["id"],
                    "title": "Smoke reference",
                    "url": None,
                    "excerpt": "Checkpoint persists graph state.",
                    "chunk_index": 0,
                }
            ]
            db.commit()
        reopened = a.get(f"/api/courses/{cid}").json()["nodes"][0]
        assert reopened.get("lesson_citations"), "Saved citations must survive re-entry"
        pending = a.post(
            "/api/courses",
            json={
                "goal": "Learn Python",
                "background": "beginner",
                "minutes_per_day": 20,
            },
        ).json()
        task_id = pending["task_id"]
        assert a.post(f"/api/tasks/{task_id}/cancel").json()["status"] == "cancelled"
        assert a.post(f"/api/tasks/{task_id}/retry").json()["status"] == "queued"
        assert b.get(f"/api/tasks/{task_id}").status_code == 404
        # A cancel request with an older identity-map snapshot cannot overwrite success.
        from backend.models import Task, User
        from backend.main import cancel_task

        with SessionLocal() as stale:
            old = stale.get(Task, task_id)
            owner = stale.get(User, a.get("/api/me").json()["id"])
            with SessionLocal() as writer:
                finished = writer.get(Task, task_id)
                finished.status = "succeeded"
                writer.commit()
            assert old.status == "queued"
            assert cancel_task(task_id, owner, stale)["status"] == "succeeded"
        assert a.post(f"/api/tasks/{task_id}/retry").status_code == 409
        assert (
            a.request("DELETE", "/api/me", json={"password": "wrong"}).status_code
            == 401
        )
        assert (
            a.request(
                "DELETE", "/api/me", json={"password": "AtlasSmoke123!"}
            ).status_code
            == 200
        )
        assert a.get("/api/me").status_code == 401
        assert b.get("/api/me").status_code == 200
    print(
        "PASS: sessions, ownership, curated lesson, answer secrecy, idempotency, RAG, memory, export, tasks and account deletion"
    )


if __name__ == "__main__":
    run()
