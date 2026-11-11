"""Focused DB/source/async provenance checks; model replies are explicit fixtures.
Run: .venv-atlas/bin/python -m backend.tests.memory_provenance_smoke
Uses temporary SQLite databases and disables dotenv before backend imports.
"""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

folder = tempfile.TemporaryDirectory(prefix="atlas-memory-")
os.environ.update(PYTHON_DOTENV_DISABLED="1", DATABASE_URL="sqlite:///" + str(Path(folder.name) / "smoke.db"), ATLAS_DATA_DIR=folder.name, WORKER_MODE="disabled")
from fastapi import HTTPException
from backend import memory as service
from backend.database import Base, engine, SessionLocal
from backend.models import (User, Course, Node, Memory, MemoryMetadata, MemoryRevision,
    MemoryProfile, MemoryWriteReceipt, TutorSession, TutorTurn, TutorEvent, Exercise, Attempt, LearningEvidence)
from backend.model_providers import ModelError
from backend.tutor.mutations import mutation_scope
from backend.tutor.store import LostLease


def denied(status, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
    else:
        raise AssertionError("operation should have been denied")


def ids(result):
    return {item["id"] for item in result["memories"]}


Base.metadata.create_all(engine)
with SessionLocal() as db:
    db.add_all([User(id=1, email="memory@smoke", hashed_password="unused"), User(id=2, email="foreign@smoke", hashed_password="unused")]); db.flush()
    db.add_all([Course(id="course", user_id=1, title="One", goal="Learn"), Course(id="other", user_id=1, title="Two", goal="Learn"), Course(id="foreign", user_id=2, title="Private", goal="Private")]); db.flush()
    db.add(Node(id="node", user_id=1, course_id="course", title="Node", objective="Learn", status="learning")); db.flush()
    db.add_all([TutorSession(id="session", user_id=1, course_id="course", title="Session"), TutorSession(id="other-session", user_id=1, course_id="other", title="Other"), TutorSession(id="foreign-session", user_id=2, course_id="foreign", title="Private")]); db.flush()
    db.add_all([TutorTurn(id="turn", user_id=1, session_id="session", request_id="input", input="I prefer concrete examples. Remember my goal: learn calculus.", output="I infer the user is a visual learner", status="completed"),
                TutorTurn(id="resume", user_id=1, session_id="session", request_id="resume", input="Original input", checkpoint={"resume_result": {"answer": "I need short explanations"}}, status="completed"),
                TutorTurn(id="grade", user_id=1, session_id="session", request_id="grade", input="Generated secret question: SYNTHETIC_PROMPT\nMy answer: my real answer", checkpoint={"grade_input": {"exercise_id": "exercise", "answer": "my real answer"}}, status="completed"),
                TutorTurn(id="confirm", user_id=1, session_id="session", request_id="confirm", input="Request", checkpoint={"resume_result": {"approved": True}}, status="completed"),
                TutorTurn(id="foreign-turn", user_id=2, session_id="foreign-session", request_id="private", input="private", status="completed")]); db.flush()
    db.add_all([TutorEvent(turn_id="resume", seq=3, type="user_response", payload={"content": "I need short explanations"}), TutorEvent(turn_id="confirm", seq=4, type="user_response", payload={"content": "接受这些变更"})]); db.commit()
    # Caller rollback/cancellation owns all synchronous changes.
    temporary = service.save_manual(db, 1, "rollback me")
    db.rollback()
    assert db.get(Memory, temporary["id"]) is None
    denied(404, service.save_manual, db, 1, "private", course_id="foreign")
    denied(404, service.remember_from_turn, db, 1, "foreign-turn", "private")
    denied(422, service.remember_from_turn, db, 1, "turn", "visual learner")
    denied(422, service.remember_from_turn, db, 1, "grade", "SYNTHETIC_PROMPT")
    # Initial user input remains attributable after a continuation.
    initial = service.remember_from_turn(db, 1, "resume", "Original input")
    assert initial["origin"] == "turn"
    # Production runner has already popped resume_result by the next tool.
    resumed_turn = db.get(TutorTurn, "resume")
    resumed_turn.checkpoint = {"messages": [{"role": "tool", "content": json.dumps({"answer": "I need short explanations"})}]}
    db.commit()
    denied(422, service.remember_from_turn, db, 1, "confirm", "接受这些变更")
    preference = service.remember_from_turn(db, 1, "turn", "I prefer concrete examples", "preference", facet="style", request_key="pref"); db.commit()
    assert preference["course_id"] is None
    assert service.remember_from_turn(db, 1, "turn", "I prefer concrete examples", "preference", facet="style", request_key="pref")["id"] == preference["id"]
    assert service.remember_from_turn(db, 1, "turn", "I prefer concrete examples", "preference", facet="style", request_key="pref-alias")["id"] == preference["id"]
    db.commit()
    denied(409, service.save_manual, db, 1, "different", request_key="pref-alias")
    answer = service.remember_from_turn(db, 1, "grade", "my real answer", request_key="answer")
    resume = service.remember_from_turn(db, 1, "resume", "short explanations", request_key="resume")
    course = service.save_manual(db, 1, "course-bound calculus goal", course_id="course", request_key="course")
    other = service.save_manual(db, 1, "other-bound calculus goal", course_id="other")
    personal = service.save_manual(db, 1, "personal calculus goal")
    foreign = service.save_manual(db, 2, "foreign calculus goal", course_id="foreign")
    db.commit()
    assert ids(service.recall(db, 1, "calculus")) == {preference["id"], personal["id"]}
    selected = ids(service.recall(db, 1, "calculus", "course"))
    assert course["id"] in selected and other["id"] not in selected and foreign["id"] not in selected
    # New marker is sufficient even when the tool receipt is compacted away.
    resumed_event = db.query(TutorEvent).filter_by(turn_id="resume", seq=3).one()
    resumed_event.payload = {"content": "I need short explanations", "origin": "user_input"}
    resumed_turn.checkpoint = {}
    db.commit()
    marked = service.remember_from_turn(db, 1, "resume", "I need short", request_key="marked")
    assert marked["origin"] == "turn"
    db.commit()
    detail = service.inspect_memory(db, 1, marked["id"])
    assert detail["evidence"][0]["seq"] == 3 and detail["evidence"][0]["url"] == "/chat?session=session"
    denied(404, service.inspect_memory, db, 2, resume["id"])
    # New explicit facet value supersedes the old value; forgetting never
    # brings an older preference back into context.
    new = service.save_manual(db, 1, "Use short explanations", "preference", facet="style", request_key="new-style"); db.commit()
    assert service.inspect_memory(db, 1, preference["id"])["memory"]["status"] == "superseded"
    service.forget_memory(db, 1, new["id"], 1); db.commit()
    assert not any(item["category"] == "preference" for item in service.recall(db, 1, "style")["memories"])
    edited = service.update_memory(db, 1, new["id"], "Still forgotten", expected_revision=2); db.commit()
    assert edited["status"] == "forgotten" and edited["revision"] == 3
    denied(409, service.update_memory, db, 1, new["id"], "stale", expected_revision=1)
    denied(409, service.forget_memory, db, 1, new["id"], expected_revision=1)
    with SessionLocal() as stale:
        stale.get(Memory, personal["id"])
        service.update_memory(db, 1, personal["id"], "personal calculus updated", 1); db.commit()
        denied(409, service.update_memory, stale, 1, personal["id"], "clobber", 1)
    # Legacy records stay visible and do not gain invented evidence on read.
    legacy = Memory(id="legacy", user_id=1, content="historical calculus fact", category="note")
    db.add(legacy); db.commit()
    before = db.query(MemoryMetadata).count()
    assert service.inspect_memory(db, 1, "legacy")["memory"]["source_status"] == "legacy_unverified"
    assert "legacy" not in ids(service.recall(db, 1, "historical"))
    service.get_profile(db, 1)
    assert db.query(MemoryMetadata).count() == before
    confirmed = service.update_memory(db, 1, "legacy", legacy.content, 1); db.commit()
    assert confirmed["origin"] == "manual" and confirmed["revision"] == 2 and "legacy" in ids(service.recall(db, 1, "historical"))
    assert len(service.inspect_memory(db, 1, "legacy")["history"]) == 2
    # Existing 12k API limit remains compatible with same-text legacy confirmation.
    db.add(Memory(id="long-legacy", user_id=1, category="note", content="long authored record " * 400 + "end")); db.commit()
    long_original = db.get(Memory, "long-legacy").content
    long_confirmed = service.update_memory(db, 1, "long-legacy", long_original, 1); db.commit()
    assert long_confirmed["content"] == long_original and long_confirmed["origin"] == "manual"
    # Source mutations/missing rows invalidate actual raw-user references.
    turn = db.get(TutorTurn, "grade"); turn.checkpoint = {"grade_input": {"answer": "corrected source"}}; db.commit()
    assert service.inspect_memory(db, 1, answer["id"])["memory"]["source_status"] == "source_changed"
    db.delete(db.get(TutorTurn, "resume")); db.commit()
    assert service.inspect_memory(db, 1, resume["id"])["memory"]["source_status"] == "source_missing"
    assert resume["id"] not in ids(service.recall(db, 1, "short", "course"))
    # Assessment refs expose submitted answers only and track grading validity.
    exercise = Exercise(id="exercise", user_id=1, node_id="node", type="open", prompt="Question", correct_answer="SECRET_STANDARD_ANSWER", explanation="SECRET_EXPLANATION")
    db.add(exercise); db.flush()
    attempt = Attempt(id="attempt", user_id=1, exercise_id=exercise.id, node_id="node", request_id="attempt", answer="my actual attempt", score=20, feedback="Feedback", correct_answer="SECRET_STANDARD_ANSWER", mastery=20, passed=False)
    db.add(attempt); db.flush()
    learning = LearningEvidence(user_id=1, attempt_id=attempt.id, node_id="node", exercise_id=exercise.id, skill_type="concept", difficulty="beginner", score=20, independent=True)
    db.add(learning); db.flush()
    assessment = Memory(id="assessment", user_id=1, course_id="course", category="misconception", content="calculus misconception from submitted answer")
    db.add(assessment); db.flush()
    service.sync_assessment_memory(db, assessment, attempt.id); db.commit()
    public = json.dumps(service.inspect_memory(db, 1, assessment.id))
    assert "my actual attempt" in public and "SECRET_STANDARD_ANSWER" not in public and "SECRET_EXPLANATION" not in public
    assert assessment.id in ids(service.recall(db, 1, "calculus", "course"))
    exercise.revision += 1; db.commit()
    assert assessment.id not in ids(service.recall(db, 1, "calculus", "course"))
    service.sync_assessment_memory(db, assessment, attempt.id); db.commit()
    service.forget_memory(db, 1, assessment.id); db.commit()
    assessment.content = "new diagnosis"; service.sync_assessment_memory(db, assessment, attempt.id); db.commit()
    assert service.inspect_memory(db, 1, assessment.id)["memory"]["status"] == "forgotten"
    assessment.category = "invalidated_assessment"; service.sync_assessment_memory(db, assessment); db.commit()
    assert service.inspect_memory(db, 1, assessment.id)["memory"]["source_status"] == "invalidated"
    # Hard deletion preserves the original DELETE contract, including cascades.
    removable = service.save_manual(db, 1, "delete me", request_key="delete"); db.commit()
    service.update_memory(db, 1, removable["id"], "delete revised", 1); db.commit()
    service.delete_memory(db, 1, removable["id"]); db.commit()
    assert db.query(MemoryRevision).filter_by(memory_id=removable["id"]).count() == 0
    assert db.get(MemoryMetadata, removable["id"]) is None
    assert db.query(MemoryWriteReceipt).filter_by(memory_id=removable["id"]).count() == 0
print("PASS writes: ownership/scope, true input/resume/grade provenance, idempotency, conflict, forget, legacy confirmation, assessment invalidation, read-only, cascades")

calls = []
async def model(messages, user_id, step, **kwargs):
    assert step == "memory_consolidation"
    facts = json.loads(messages[-1]["content"])["facts"]
    assert len(facts) <= 32 and sum(len(item["content"]) for item in facts) <= 18000
    calls.append(facts)
    return {"groups": [{"label": "其他记录", "claims": [{"memory_id": item["memory_id"], "revision": item["revision"], "quote": item["content"][:600]} for item in facts[:12]]}]}

async def main():
    with SessionLocal() as db, patch("backend.llm.complete", model):
        profile = await service.consolidate(db, 1, request_key="profile")
        assert profile["status"] == "ready" and profile["groups"]
        count = len(calls)
        assert (await service.consolidate(db, 1, request_key="profile"))["id"] == profile["id"]
        assert len(calls) == count
        # The replay fast path must release its write lock before another
        # connection emits an event or persists a business mutation.
        with SessionLocal() as writer:
            writer.connection().exec_driver_sql("PRAGMA busy_timeout=200")
            service.save_manual(writer, 1, "write after replay")
            writer.commit()
        claim = profile["groups"][0]["claims"][0]
        service.update_memory(db, 1, claim["memory_id"], "Changed authored fact", claim["revision"]); db.commit()
        assert service.get_profile(db, 1)["status"] == "stale" and not service.recall(db, 1, "")["profile"]["groups"]
        assert (await service.consolidate(db, 1, request_key="profile"))["status"] == "stale"
    # Fabricated ids, revisions, quotes, or inferred labels are never accepted.
    for index, bad in enumerate([
        {"label": "其他记录", "claims": [{"memory_id": "invented", "revision": 1, "quote": "claim"}]},
        {"label": "其他记录", "claims": [{"memory_id": calls[0][0]["memory_id"], "revision": 999, "quote": "claim"}]},
        {"label": "用户是天才", "claims": []},
        {"label": "其他记录", "claims": [{"memory_id": "legacy", "revision": 2, "quote": "invented personality statement"}]},
    ]):
        async def fabricated(*args, **kwargs): return {"groups": [bad]}
        with SessionLocal() as db, patch("backend.llm.complete", fabricated):
            try: await service.consolidate(db, 1, request_key="fabricated-" + str(index))
            except HTTPException as exc: assert exc.status_code == 422
            else: raise AssertionError("fabricated profile was accepted")
            assert service.get_profile(db, 1)["status"] == "failed"
            assert not service.get_profile(db, 1)["groups"]
    async def unavailable(*args, **kwargs): raise ModelError("fixture unavailable")
    with SessionLocal() as db, patch("backend.llm.complete", unavailable):
        fallback = await service.consolidate(db, 1, request_key="fallback")
        assert fallback["status"] == "ready" and fallback["method"] == "extractive_fallback"
    # I/O releases the transaction, then rechecks newly added facts too.
    async def concurrent(messages, user_id, step, **kwargs):
        with SessionLocal() as concurrent_db:
            service.save_manual(concurrent_db, 1, "arrived during model I/O"); concurrent_db.commit()
        return await model(messages, user_id, step, **kwargs)
    with SessionLocal() as db, patch("backend.llm.complete", concurrent):
        stale = await service.consolidate(db, 1, request_key="race")
        assert stale["status"] == "stale" and stale["groups"] == []
    # Actual source invalidation, even with unchanged Memory rows, is fenced.
    with SessionLocal() as db:
        raw = service.remember_from_turn(db, 1, "turn", "learn calculus", scope="personal", request_key="source-race"); db.commit()
    async def changed_source(messages, user_id, step, **kwargs):
        with SessionLocal() as other:
            turn = other.get(TutorTurn, "turn"); turn.input = "source revised during I/O"; other.commit()
        return await model(messages, user_id, step, **kwargs)
    with SessionLocal() as db, patch("backend.llm.complete", changed_source):
        stale = await service.consolidate(db, 1, request_key="source-race-profile")
        assert stale["status"] == "stale" and not stale["groups"]
    # Mutation owner cancellation cannot commit ready/failed after I/O.
    with SessionLocal() as db:
        db.add(TutorTurn(id="owner", user_id=1, session_id="session", request_id="owner", input="organize", status="running", worker_token="worker")); db.commit()
    async def cancelled(messages, user_id, step, **kwargs):
        with SessionLocal() as other:
            owner = other.get(TutorTurn, "owner"); owner.status = "cancelled"; owner.worker_token = None; other.commit()
        return await model(messages, user_id, step, **kwargs)
    with SessionLocal() as db, patch("backend.llm.complete", cancelled):
        with mutation_scope("owner", "worker"):
            try: await service.consolidate(db, 1, request_key="cancel")
            except LostLease: pass
            else: raise AssertionError("cancelled owner published a profile")
        receipt = db.query(MemoryProfile).filter_by(request_key="cancel").one()
        assert receipt.status == "pending" and not receipt.groups
        with patch("backend.llm.complete", model):
            assert (await service.consolidate(db, 1, request_key="cancel"))["status"] == "pending"
            assert (await service.consolidate(db, 1, request_key="explicit-retry"))["status"] == "ready"
    print("PASS profiles: single model call, exact claims, failure/fallback, stale facts/source, lease cancellation, explicit retry")

asyncio.run(main())

# Exercise actual Alembic 0007 -> 0008 preservation, not create_all only.
migration_db = Path(folder.name) / "migration.db"
migration_env = dict(os.environ, DATABASE_URL="sqlite:///" + str(migration_db))
def migrate(revision):
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], env=migration_env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
migrate("20261110_0007")
with sqlite3.connect(migration_db) as conn:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO atlas_users(id,email,full_name,hashed_password,is_admin,preferences,created_at,updated_at) VALUES(1,'migration@smoke','Existing','unused',0,'{\"theme\":\"dark\"}','old','old')")
    conn.execute("INSERT INTO atlas_memories(id,user_id,course_id,category,content,created_at,updated_at) VALUES('historical',1,NULL,'preference','Retain exact bytes','old-created','old-updated')")
    before = conn.execute("SELECT * FROM atlas_memories").fetchall()
    user_before = conn.execute("SELECT * FROM atlas_users").fetchall()
migrate("head")
with sqlite3.connect(migration_db) as conn:
    assert conn.execute("SELECT * FROM atlas_memories").fetchall() == before
    assert conn.execute("SELECT * FROM atlas_users").fetchall() == user_before
    assert conn.execute("SELECT COUNT(*) FROM atlas_memory_metadata").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
print("PASS migration: real 0007 rows/preferences unchanged; no fabricated metadata; FK clean")
