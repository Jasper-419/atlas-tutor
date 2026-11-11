"""Small transactional boundaries for admission, checkpointing and event replay."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, text

from backend.database import SessionLocal, engine
from backend.models.domain import now
from backend.models.tutor import TutorEvent, TutorSession, TutorTurn

ACTIVE = {"queued", "running", "waiting_input", "waiting_confirmation"}
TERMINAL = {"completed", "failed", "cancelled"}
LEASE_SECONDS = 90


class LostLease(Exception):
    pass


def serialize_session(item):
    return {
        key: getattr(item, key)
        for key in (
            "id",
            "title",
            "course_id",
            "node_id",
            "mode",
            "created_at",
            "updated_at",
        )
    }


def public_action(value):
    if not value:
        return None
    return {
        key: value[key]
        for key in ("action_id", "kind", "title", "question", "changes", "exercise_id")
        if key in value
    }


def serialize_turn(item):
    result = {
        key: getattr(item, key)
        for key in (
            "id",
            "session_id",
            "request_id",
            "status",
            "input",
            "output",
            "error",
            "last_seq",
            "created_at",
            "updated_at",
        )
    }
    result["pending_action"] = public_action(item.pending_action)
    agent = (item.checkpoint or {}).get("agent", {})
    result["capability"] = agent.get("capability", agent.get("profile", "tutor"))
    result["result"] = agent.get("result")
    return result


def write_lock(db):
    if engine.dialect.name == "sqlite":
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))


def lock_turn(db, identifier, token=None):
    turn = (
        db.query(TutorTurn)
        .filter_by(id=identifier)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not turn or (
        token is not None and (turn.worker_token != token or turn.status != "running")
    ):
        raise LostLease()
    return turn


def add_event(db, turn, kind, payload):
    turn.last_seq += 1
    turn.updated_at = now()
    db.add(TutorEvent(turn_id=turn.id, seq=turn.last_seq, type=kind, payload=payload))
    return turn.last_seq


def emit(identifier, kind, payload, token=None, checkpoint=None):
    with SessionLocal() as db:
        write_lock(db)
        turn = lock_turn(db, identifier, token)
        if checkpoint is not None:
            turn.checkpoint = checkpoint
        if kind == "content":
            turn.output += payload["text"]
        elif kind == "content_reset":
            turn.output = payload["text"]
        seq = add_event(db, turn, kind, payload)
        db.commit()
        return seq


def checkpoint(identifier, token, value):
    with SessionLocal() as db:
        write_lock(db)
        turn = lock_turn(db, identifier, token)
        turn.checkpoint = value
        turn.updated_at = now()
        db.commit()


def heartbeat(identifier, token):
    with SessionLocal() as db:
        changed = (
            db.query(TutorTurn)
            .filter_by(id=identifier, worker_token=token, status="running")
            .update(
                {
                    "lease_until": (
                        datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
                    ).isoformat()
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return bool(changed)


def claim():
    with SessionLocal() as db:
        eligible = or_(
            TutorTurn.status == "queued",
            and_(
                TutorTurn.status == "running",
                or_(TutorTurn.lease_until.is_(None), TutorTurn.lease_until < now()),
            ),
        )
        item = (
            db.query(TutorTurn).filter(eligible).order_by(TutorTurn.created_at).first()
        )
        if not item:
            return None
        identifier, token = item.id, str(uuid4())
        changed = (
            db.query(TutorTurn)
            .filter(TutorTurn.id == identifier, eligible)
            .update(
                {
                    "status": "running",
                    "worker_token": token,
                    "lease_until": (
                        datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
                    ).isoformat(),
                    "updated_at": now(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return (identifier, token) if changed else None


def admit(db, session, content, request_id, checkpoint_data=None):
    write_lock(db)
    session = (
        db.query(TutorSession)
        .filter_by(id=session.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    previous = (
        db.query(TutorTurn)
        .filter_by(session_id=session.id, request_id=request_id)
        .first()
    )
    if previous:
        if previous.input != content:
            raise HTTPException(409, "request_id 已用于另一条消息。")
        return previous
    active = (
        db.query(TutorTurn)
        .filter(TutorTurn.session_id == session.id, TutorTurn.status.in_(ACTIVE))
        .first()
    )
    if active:
        raise HTTPException(409, "请先完成当前回复、回答问题或处理变更预览。")
    turn = TutorTurn(
        user_id=session.user_id,
        session_id=session.id,
        request_id=request_id,
        input=content,
        checkpoint=checkpoint_data or {},
    )
    db.add(turn)
    if session.title == "新对话":
        session.title = content[:70]
    session.updated_at = now()
    db.flush()
    add_event(db, turn, "status", {"status": "queued", "message": "正在准备学习上下文"})
    db.commit()
    return turn
