"""Focused contract smoke. External model completions are explicit fixtures only.

Run: .venv-atlas/bin/python -m backend.tests.practice_contracts_smoke
Uses temporary SQLite and never loads dotenv or a live model credential.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

folder = tempfile.TemporaryDirectory(prefix="atlas-practice-contract-")
os.environ.update(
    PYTHON_DOTENV_DISABLED="1", ATLAS_DATA_DIR=folder.name,
    DATABASE_URL="sqlite:///" + str(Path(folder.name) / "smoke.db"),
    WORKER_MODE="disabled", EMBEDDING_MODEL="",
)

from fastapi import HTTPException
from backend.database import Base, SessionLocal, engine
from backend import learning, practice_contracts as contracts, assessment_repair
from backend.llm import ModelError
from backend.models import (User, Course, Node, Exercise, LearningEvidence, PracticeBatch,
    ExerciseMetadata, NodeLearningState, NodeTeachingState, Source, Chunk, TutorSession, TutorTurn)
from backend.tutor.mutations import mutation_scope
from backend.tutor.store import LostLease


def question(prompt="Python 中名字与对象是什么关系？"):
    return {"exercises": [{"type": "open", "prompt": prompt, "options": [],
        "correct_answer": "名字绑定到对象；对象具有身份、类型和值。",
        "explanation": "赋值会建立或改变名字与对象的绑定。", "skill_type": "concept"}]}


async def wrong_scope_fixture(messages, user_id, step, **kwargs):
    """External model fixture deliberately refuses ambiguous requested focus."""
    payload = json.loads(messages[-1]["content"])
    if step == "practice_contract_scope":
        return {"context_hash": payload["context_hash"], "decision": "uncertain",
            "interpreted_focus": "定义与例子", "reason": "未说明想练习哪个概念的定义与例子。", "evidence": []}
    if step == "adaptive_practice":
        return question()
    raise AssertionError(step)


def external_fixture(mode, calls):
    """External scope/verifier/generator replies; domain code remains real."""
    async def fixture(messages, user_id, step, **kwargs):
        calls.append(step)
        payload = json.loads(messages[-1]["content"])
        if step == "practice_contract_scope":
            return {"context_hash": payload["context_hash"], "decision": "in_scope",
                "interpreted_focus": "Python名字与对象的绑定关系", "reason": "重点属于节点声明的知识范围。",
                "evidence": [{"source_ref": "node_scope", "quote": payload["node"]["title"]}]}
        if step in {"adaptive_practice", "practice_contract_repair"}:
            result = question("场景" + mode + ("修正" if step.endswith("repair") else "初稿") + "：解释Python名字与对象的绑定。")
            if mode == "choice":
                result["exercises"][0].update(type="choice", options=["名字绑定对象", "名字就是对象"], correct_answer="名字绑定对象")
            return result
        if step == "practice_contract_verify":
            evidence = [{"source_ref": payload["sources"][0]["source_ref"],
                "quote": payload["sources"][0]["text"][:25]}]
            row = {"index": 0, "focus": "pass", "answer_key": "pass", "source_support": "pass",
                "reason": "独立判断名字是到对象的绑定，参考答案与资料一致。", "evidence": evidence}
            if mode == "repair" and calls.count(step) == 1:
                row["answer_key"] = "fail"
            if mode == "fabricated":
                evidence[0]["quote"] = "这一段文字在任何实际资料里都不存在。"
            if mode == "boolean":
                row["answer_key"] = True
            if mode == "bad-hash":
                payload["items_hash"] = "0" * 64
            if mode == "source-change":
                with SessionLocal() as other:
                    other.get(Source, "source").version += 1
                    other.commit()
            if mode == "cancel":
                with SessionLocal() as other:
                    other.get(TutorTurn, "turn").status = "cancelled"
                    other.commit()
            return {"context_hash": payload["context_hash"], "items_hash": payload["items_hash"], "items": [row]}
        raise AssertionError(step)
    return fixture


def snapshot(db):
    return tuple(db.query(model).count() for model in (Exercise, PracticeBatch, LearningEvidence, NodeLearningState, NodeTeachingState))


async def expected_error(exc_type, operation):
    try:
        await operation
    except exc_type as exc:
        return exc
    raise AssertionError("expected " + exc_type.__name__)


async def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(id=1, email="practice@smoke", hashed_password="x")); db.flush()
        db.add(Course(id="course", user_id=1, title="Python", goal="学习Python")); db.flush()
        db.add(Node(id="node", user_id=1, course_id="course", title="Python 名字与对象",
            objective="区分名字、对象与绑定", status="learning",
            content="Python 的名字绑定到对象；对象具有身份、类型和值。赋值会建立或改变绑定。"))
        db.commit()
        with patch.object(learning, "complete", wrong_scope_fixture), patch.object(contracts, "complete", wrong_scope_fixture):
            try:
                await learning.generate_practice(db, 1, "node", "定义与例子", count=1, request_key="wrong-scope")
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("ambiguous focus was accepted and unrelated practice persisted")
        assert snapshot(db) == (0, 0, 0, 0, 0)
        async def off_topic_fixture(messages, user_id, step, **kwargs):
            result = await wrong_scope_fixture(messages, user_id, step, **kwargs)
            result.update(decision="off_topic", interpreted_focus="几何中线的定义", reason="几何知识不属于Python名字与对象节点。")
            return result
        with patch.object(contracts, "complete", off_topic_fixture):
            exc = await expected_error(HTTPException, learning.generate_practice(db, 1, "node", "几何中线", count=1, request_key="off-topic"))
            assert exc.status_code == 409 and "切换节点" in exc.detail
        assert snapshot(db) == (0, 0, 0, 0, 0)
        calls, queries = [], []
        async def search_fixture(db, user_id, course_id, query):
            queries.append(query)
            return []
        for mode in ("valid", "repair", "fabricated", "boolean", "bad-hash", "choice"):
            calls.clear()
            fixture = external_fixture(mode, calls)
            before = snapshot(db)
            with patch.object(learning, "complete", fixture), patch.object(contracts, "complete", fixture), patch.object(learning, "search", search_fixture):
                if mode in {"fabricated", "boolean", "bad-hash"}:
                    await expected_error(ModelError, learning.generate_practice(db, 1, "node", "Python绑定", count=1, request_key=mode))
                    assert snapshot(db) == before
                    assert calls.count("practice_contract_repair") == 1 and calls.count("practice_contract_verify") == 2
                    continue
                public = await learning.generate_practice(db, 1, "node", "Python绑定", count=1, request_key=mode)
                assert "Python绑定" in queries[-1], "explicit focus missing from retrieval"
                assert len(public) == 1 and "correct_answer" not in public[0] and "explanation" not in public[0]
                receipt = learning.practice_validation(db, 1, "node", public)
                assert receipt["method"] == "model_assisted" and receipt["repaired"] == (mode == "repair")
                encoded = json.dumps(receipt, ensure_ascii=False)
                assert "quote" not in encoded and "名字绑定到对象" not in encoded and "hash" not in encoded
                batch = db.query(PracticeBatch).filter_by(request_key=mode).one()
                assert batch.validation["result_hash"] and batch.validation["sources"]
                assert batch.request_spec == {"focus": "Python绑定", "difficulty": "adaptive", "count": 1}
                call_count, query_count = len(calls), len(queries)
                assert await learning.generate_practice(db, 1, "node", "Python绑定", count=1, request_key=mode) == public
                assert len(calls) == call_count and len(queries) == query_count, "replay regenerated"
                exc = await expected_error(HTTPException, learning.generate_practice(db, 1, "node", "改动重点", count=1, request_key=mode))
                assert exc.status_code == 409
                if mode == "choice":
                    assert db.query(LearningEvidence).count() == 0
                    assessment = await learning.submit_answer(db, 1, public[0]["id"], "名字绑定对象", "answer")
                    assert assessment["score"] == 100 and db.query(LearningEvidence).count() == 1
        # A real confirmed repair changes the contract but preserves the private
        # generation receipt. It must no longer certify the current question.
        repaired_batch = db.query(PracticeBatch).filter_by(request_key="choice").one()
        immutable_receipt = json.dumps(repaired_batch.validation, sort_keys=True)
        original_revision = db.get(Exercise, public[0]["id"]).revision
        async def repair_fixture(messages, user_id, step, **kwargs):
            assert step == "question_repair_preview"
            return {"mode": "correct", "reason": "External fixture for receipt invalidation only.",
                "correct_answer": "名字就是对象", "rubric": "更正后的单选评分标准。",
                "explanation": "用于核对确认修复后旧核验回执失效。"}
        with patch.object(assessment_repair, "complete", repair_fixture):
            proposal = await assessment_repair.propose_repair(db, 1, public[0]["id"], "检查答案合同", "receipt-repair")
            db.commit()
            await assessment_repair.apply_repair(db, 1, proposal)
            db.commit()
        assert db.get(Exercise, public[0]["id"]).revision == original_revision + 1
        assert learning.practice_validation(db, 1, "node", public) is None, "repaired exercise retained obsolete passed receipt"
        assert json.dumps(repaired_batch.validation, sort_keys=True) == immutable_receipt, "historical receipt was overwritten"
        valid_batch = db.query(PracticeBatch).filter_by(request_key="valid").one()
        current_contracts = contracts.exercise_fingerprints(db, 1, "node", valid_batch.exercise_ids)
        legacy_receipt = {key: value for key, value in valid_batch.validation.items() if key != "exercise_contracts"}
        assert contracts.public_receipt(legacy_receipt, current_contracts) is None, "unbound historical receipt certified current content"
        assert contracts.public_receipt(valid_batch.validation) is None, "receipt projected without current owner contract check"
        valid_public = learning._batch_result(db, 1, valid_batch)
        valid_id = valid_public[0]["id"]
        # Each grading-relevant field must invalidate independently, even when
        # another edit path forgets to increment revision. Roll back each probe.
        mutations = [(Exercise, key, value) for key, value in (
            ("prompt", "Changed question"), ("options", ["Changed option"]),
            ("correct_answer", "Changed private answer"), ("explanation", "Changed private explanation"),
            ("rubric", "Changed rubric"), ("revision", 99), ("voided", True),
        )] + [(ExerciseMetadata, key, value) for key, value in (
            ("skill_type", "application"), ("difficulty", "advanced"), ("focus", "Changed focus"),
            ("criteria", [{"id": "changed", "max_points": 100}]),
        )]
        for model, field, value in mutations:
            row = db.get(Exercise, valid_id) if model is Exercise else db.query(model).filter_by(exercise_id=valid_id).one()
            setattr(row, field, value)
            assert learning.practice_validation(db, 1, "node", valid_public) is None, "receipt ignored changed " + field
            db.rollback()
            assert learning.practice_validation(db, 1, "node", valid_public), "rollback did not restore original valid contract"
        # Historical batch replays without invoking a new checker and omits receipt.
        old = PracticeBatch(user_id=1, node_id="node", request_key="historic",
            request_spec={"focus": "历史", "difficulty": "adaptive", "count": 1}, exercise_ids=[public[0]["id"]])
        db.add(old); db.commit()
        async def no_model(*args, **kwargs):
            raise AssertionError("historical replay invoked model")
        with patch.object(learning, "complete", no_model), patch.object(contracts, "complete", no_model):
            await learning.generate_practice(db, 1, "node", "历史", count=1, request_key="historic")
        assert contracts.public_receipt(old.validation) is None
        # Independent requests with the same key race through generation but
        # serialize at the existing node lock and reuse the sole persisted batch.
        db.rollback()
        race_fixture = external_fixture("race", [])
        async def yielding_fixture(*args, **kwargs):
            await asyncio.sleep(0)
            return await race_fixture(*args, **kwargs)
        async def concurrent_request():
            with SessionLocal() as worker:
                return await learning.generate_practice(worker, 1, "node", "Python绑定", count=1, request_key="race")
        with patch.object(learning, "complete", yielding_fixture), patch.object(contracts, "complete", yielding_fixture), patch.object(learning, "search", search_fixture):
            first, second = await asyncio.gather(concurrent_request(), concurrent_request())
            assert first == second
        assert db.query(PracticeBatch).filter_by(request_key="race").count() == 1
        db.rollback()
        # Real owned retrieved chunks are read from DB, never provider excerpts.
        db.add(Source(id="source", user_id=1, course_id="course", title="Python资料")); db.flush()
        db.add(Chunk(id="chunk", user_id=1, course_id="course", source_id="source", chunk_index=0,
            content="Python 的名字绑定到对象；对象具有身份、类型和值。"))
        db.add(TutorSession(id="session", user_id=1, course_id="course")); db.flush()
        db.add(TutorTurn(id="turn", user_id=1, session_id="session", request_id="cancel", status="running", worker_token="token", input="练习"))
        db.commit()
        async def chunk_search(*args, **kwargs):
            return [{"id": "chunk", "excerpt": "FAKE excerpt cannot become evidence"}]
        checked_context = contracts.make_context(db, 1, db.get(Node, "node"), {}, "beginner",
            [{"id": "chunk", "excerpt": "FAKE excerpt cannot become evidence"}], None)
        assert checked_context["sources"][-1]["text"] == db.get(Chunk, "chunk").content
        for mode in ("source-change", "cancel"):
            fixture = external_fixture(mode, [])
            before = snapshot(db)
            with patch.object(learning, "complete", fixture), patch.object(contracts, "complete", fixture), patch.object(learning, "search", chunk_search):
                if mode == "cancel":
                    with mutation_scope("turn", "token"):
                        await expected_error(LostLease, learning.generate_practice(db, 1, "node", "Python绑定", count=1, request_key=mode))
                else:
                    exc = await expected_error(HTTPException, learning.generate_practice(db, 1, "node", "Python绑定", count=1, request_key=mode))
                    assert exc.status_code == 409
                assert snapshot(db) == before, mode + " persisted partial state"
    print("PASS practice contracts: scope zero-write, focus retrieval, strict decisions/hash/real quotes, one repair, private receipt/current-contract binding after repair/void/metadata, replay/history/concurrent batch, answer evidence, source race and cancellation rollback")


if __name__ == "__main__":
    asyncio.run(main())
