"""Cross-record memory contracts against the real API and isolated SQLite."""

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="atlas-record-memory-") as folder:
        os.environ.update(
            PYTHON_DOTENV_DISABLED="1", ATLAS_DATA_DIR=folder,
            DATABASE_URL="sqlite:///" + str(Path(folder) / "atlas.db"),
            ATLAS_CHECKPOINT_PATH=str(Path(folder) / "checkpoints.db"),
            CHECKPOINT_DATABASE_URL="", ATLAS_CREDENTIALS_KEY="", WORKER_MODE="disabled",
        )
        from fastapi.testclient import TestClient
        from backend.database import SessionLocal
        from backend.main import app
        from backend.models import Attempt, Exercise, LearningEvidence, NotebookNote, TutorEvent, TutorSession, TutorTurn

        def ok(response, status=200):
            assert response.status_code == status, (response.status_code, response.text[:400])
            return response.json()

        def register(client, name):
            return ok(client.post("/api/auth/register", json={
                "email": f"{name}@record-fixture.invalid", "password": "RecordFixture123!", "full_name": name,
            }))

        calls = []
        shared = "向量索引需要记录模型身份。"
        reply = "我希望先理解索引恢复再实践。"

        async def model(messages, user_id, step, **_):
            assert step == "memory_record_organization"
            data = json.loads(messages[-1]["content"])
            assert "PRIVATE_FIXTURE" not in json.dumps(data)
            calls.append(data["records"])
            return {"items": [{"source": item["source"], "quote": item["text"][:200]}
                              for item in data["records"]]}

        with TestClient(app) as owner, TestClient(app) as stranger, patch("backend.llm.complete", model):
            user = register(owner, "owner")
            other = register(stranger, "stranger")
            template = ok(owner.get("/api/templates"))[0]
            course = ok(owner.post(f"/api/templates/{template['id']}/enroll"))
            foreign = ok(stranger.post(f"/api/templates/{template['id']}/enroll"))
            course_id, node_id = course["id"], course["nodes"][0]["id"]

            def note(text, course_key=course_id, client=owner):
                return ok(client.post("/api/notes", json={"title": "索引笔记", "content": text, "course_id": course_key}))

            def organize(key, course_key=course_id, client=owner, expected=200):
                return ok(client.post("/api/me/memory/organize", json={"request_id": key, "course_id": course_key}), expected)

            def memories():
                return ok(owner.get("/api/me/memories"))

            def recall(query):
                return ok(owner.get("/api/me/memory/recall", params={"course_id": course_id, "q": query}))["memories"]

            original_note = note(shared)
            note("PRIVATE_FIXTURE_OTHER_COURSE", None)
            note("PRIVATE_FIXTURE_OTHER_ACCOUNT", foreign["id"], stranger)
            with SessionLocal() as db:
                session = TutorSession(user_id=user["id"], course_id=course_id, title="学习对话")
                db.add(session)
                db.flush()
                turn = TutorTurn(user_id=user["id"], session_id=session.id, request_id="chat", input=shared,
                                 output="PRIVATE_FIXTURE_ASSISTANT", status="completed")
                grade_turn = TutorTurn(user_id=user["id"], session_id=session.id, request_id="grade",
                                      input="PRIVATE_FIXTURE_GENERATED_PROMPT", status="completed",
                                      checkpoint={"grade_input": {"answer": "B"}})
                exercise = Exercise(user_id=user["id"], node_id=node_id, type="choice", prompt="PRIVATE_FIXTURE_EXERCISE",
                                    correct_answer="PRIVATE_FIXTURE_REFERENCE")
                db.add_all([turn, grade_turn, exercise])
                db.flush()
                db.add_all([
                    TutorEvent(turn_id=turn.id, seq=1, type="user_response", payload={"origin": "user_input", "content": reply}),
                    TutorEvent(turn_id=turn.id, seq=2, type="user_response", payload={"origin": "confirmation", "content": "PRIVATE_FIXTURE_APPROVAL"}),
                ])
                attempt = Attempt(user_id=user["id"], exercise_id=exercise.id, node_id=node_id, request_id="answer",
                                  answer="B", score=60, feedback="", correct_answer="PRIVATE_FIXTURE_REFERENCE", mastery=0, passed=False)
                db.add(attempt)
                db.flush()
                db.add(LearningEvidence(user_id=user["id"], attempt_id=attempt.id, exercise_id=exercise.id, node_id=node_id,
                                        skill_type="recall", difficulty="beginner", score=60, independent=True))
                attempt_id, exercise_id = attempt.id, exercise.id
                db.commit()

            organize("unauthorized", course_id, stranger, 404)
            first = organize("first")
            assert first["status"] == "succeeded", first
            assert first["counts"] == {"chat": 2, "note": 1, "practice": 1, "created": 3, "merged": 1, "suppressed": 0, "changed": 0}
            shared_memory = next(row for row in memories() if row["content"] == shared)
            shared_url = f"/api/me/memories/{shared_memory['id']}"
            detail = ok(owner.get(shared_url))
            assert {item["kind"] for item in detail["evidence"]} == {"turn", "note"}
            assert detail["memory"]["revision"] == 2
            practice = next(row for row in memories() if row["category"] == "practice_record")
            assert "60 分" in practice["content"] and practice["content"].endswith("B")
            assert practice["id"] in {row["id"] for row in recall("练习")}
            assert organize("first") == first and len(calls) == 1
            assert not organize("no-new")["has_more"] and len(calls) == 1

            ok(owner.patch(f"/api/notes/{original_note['id']}", json={"content": "索引更新应保留原来的引用。", "expected_version": 1}))
            counts = ok(owner.get("/api/me/memory/audit", params={"course_id": course_id}))
            assert counts["partial"] == 1
            assert shared_memory["id"] in {row["id"] for row in recall("模型身份")}
            assert organize("note-updated")["counts"]["note"] == 1 and len(calls[-1]) == 1
            ok(owner.delete(shared_url))
            note(shared)
            assert organize("skip-deleted")["counts"]["suppressed"] == 1
            assert shared not in {row["content"] for row in memories()}
            ok(owner.post(f"/api/me/memories/{practice['id']}/forget", json={"expected_revision": practice["revision"]}))
            with SessionLocal() as db:
                db.get(Exercise, exercise_id).revision += 1
                db.get(Attempt, attempt_id).score = 70
                db.commit()
            assert organize("skip-forgotten-regrade")["counts"]["suppressed"] == 1
            assert all("70 分" not in row["content"] for row in memories())

            changing = note("旧的笔记证据会被重查。")

            async def changed_source(*args, **kwargs):
                result = await model(*args, **kwargs)
                with SessionLocal() as db:
                    row = db.get(NotebookNote, changing["id"])
                    row.content, row.version = "更正后的笔记是当前来源。", 2
                    db.commit()
                return result

            with patch("backend.llm.complete", changed_source):
                stale = organize("racing-note")
            assert stale["counts"]["changed"] == 1 and stale["has_more"]
            assert all(row["content"] != changing["content"] for row in memories())
            with patch("backend.llm.complete", return_value={"items": [{"source": "0", "quote": "模型虚构的笔记原文"}]}):
                assert organize("forged")["status"] == "failed"
            assert organize("retry-current-note")["counts"]["created"] == 1
            assert any(row["content"] == "更正后的笔记是当前来源。" for row in memories())
            with SessionLocal() as db:
                db.add(Attempt(user_id=user["id"], exercise_id=exercise_id, node_id=node_id,
                               request_id="old-grade", answer="D", score=50, feedback="",
                               correct_answer="PRIVATE_FIXTURE_REFERENCE", mastery=0, passed=False))
                db.commit()
            assert organize("older-grade")["counts"]["practice"] == 1
            assert any("50 分" in row["content"] and row["content"].endswith("D") for row in recall("练习"))
            note("笔" * 1590 + "\n长笔记尾部应在下一批整理。")
            assert organize("long-note-first")["has_more"]
            assert not organize("long-note-tail")["has_more"]
            assert any(row["content"] == "长笔记尾部应在下一批整理。" for row in memories())

        print("PASS: owned chat/note/practice organization, exact dedup, incremental cursors, audit, no resurrection, stale/forged rejection")


if __name__ == "__main__":
    main()
