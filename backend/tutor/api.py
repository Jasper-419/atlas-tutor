"""Authenticated Tutor admission, responses, cancellation and durable SSE replay."""

import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.config import get_settings
from backend.database import SessionLocal, get_db
from backend.models.domain import Course, Exercise, Message, Node, Task
from backend.models.tutor import TutorEvent, TutorSession, TutorTurn
from backend.security import current_user
from backend.serializers import task_json
from backend.tutor import paths, store
from backend.tutor.tools import owned
from backend.agent.policy import Profile
from backend.agent.capabilities import CapabilityName, get_capability
from backend.agent.service import admit_turn

router = APIRouter(prefix="/api")
DB, AUTH = Depends(get_db), Depends(current_user)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewSession(Body):
    course_id: str | None = Field(default=None, max_length=40)
    node_id: str | None = Field(default=None, max_length=40)
    title: str = Field(default="新对话", min_length=1, max_length=255)
    mode: Literal["outline", "study", "review"] = "study"


class NewTurn(Body):
    content: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=120)
    profile: Profile | None = None
    capability: CapabilityName | None = None


class Respond(Body):
    content: str | None = Field(default=None, min_length=1, max_length=12000)
    approved: bool | None = None
    action_id: str | None = Field(default=None, max_length=40)


class Answer(Body):
    exercise_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=1, max_length=120)


def with_events(db, turn):
    result = store.serialize_turn(turn)
    result["events"] = [
        {"seq": e.seq, "type": e.type, "payload": e.payload}
        for e in db.query(TutorEvent)
        .filter(
            TutorEvent.turn_id == turn.id,
            ~TutorEvent.type.in_(["content", "content_reset", "status", "done"]),
        )
        .order_by(TutorEvent.seq)
    ]
    return result


@router.get("/tutor/sessions")
def sessions(
    course_id: str | None = None, node_id: str | None = None, user=AUTH, db=DB
):
    query = db.query(TutorSession).filter_by(user_id=user.id)
    if course_id:
        owned(db, Course, course_id, user.id)
        query = query.filter_by(course_id=course_id)
    if node_id:
        owned(db, Node, node_id, user.id)
        query = query.filter_by(node_id=node_id)
    return [
        store.serialize_session(item)
        for item in query.order_by(TutorSession.updated_at.desc(), TutorSession.id.desc())
    ]


@router.post("/tutor/sessions")
def create_session(body: NewSession, user=AUTH, db=DB):
    if body.course_id:
        owned(db, Course, body.course_id, user.id)
    if body.node_id:
        node = owned(db, Node, body.node_id, user.id)
        if node.retired or (body.course_id and body.course_id != node.course_id):
            raise HTTPException(404, "节点不属于当前课程。")
        body.course_id = node.course_id
    item = TutorSession(user_id=user.id, **body.model_dump())
    # Lazily bring historical node chats into the first new-runtime session.
    has_session = (
        db.query(TutorSession.id)
        .filter_by(user_id=user.id, node_id=body.node_id)
        .first()
        if body.node_id
        else True
    )
    db.add(item)
    db.flush()
    if body.node_id and not has_session:
        history = (
            db.query(Message)
            .filter_by(user_id=user.id, node_id=body.node_id)
            .order_by(Message.created_at)
            .all()
        )
        assistants = {
            m.request_id: m for m in history if m.role == "assistant" and m.request_id
        }
        for message in history:
            if message.role != "user":
                continue
            answer = assistants.get(message.request_id)
            if answer:
                turn = TutorTurn(
                    user_id=user.id,
                    session_id=item.id,
                    request_id="legacy:" + message.id,
                    input=message.content,
                    output=answer.content,
                    status="completed",
                    created_at=message.created_at,
                )
                db.add(turn)
                db.flush()
                if answer.citations:
                    store.add_event(
                        db, turn, "citations", {"citations": answer.citations}
                    )
    db.commit()
    return store.serialize_session(item)


@router.get("/tutor/sessions/{session_id}")
def session_detail(session_id: str, user=AUTH, db=DB):
    item = owned(db, TutorSession, session_id, user.id)
    turns = (
        db.query(TutorTurn)
        .filter_by(session_id=item.id, user_id=user.id)
        .order_by(TutorTurn.created_at)
        .all()
    )
    return {
        **store.serialize_session(item),
        "turns": [with_events(db, turn) for turn in turns],
    }


@router.post("/tutor/sessions/{session_id}/turns")
def new_turn(session_id: str, body: NewTurn, user=AUTH, db=DB):
    if not body.content.strip():
        raise HTTPException(422, "消息不能为空。")
    session = owned(db, TutorSession, session_id, user.id)
    return with_events(db, admit_turn(db, session, body.content, body.request_id, profile=body.profile, capability=body.capability))


@router.post("/tutor/sessions/{session_id}/answers")
def answer(session_id: str, body: Answer, user=AUTH, db=DB):
    session = owned(db, TutorSession, session_id, user.id)
    exercise = owned(db, Exercise, body.exercise_id, user.id)
    node = owned(db, Node, exercise.node_id, user.id)
    if session.course_id != node.course_id:
        raise HTTPException(404, "题目不属于当前会话课程。")
    if not body.answer.strip():
        raise HTTPException(422, "答案不能为空。")
    store.write_lock(db)
    session = (
        db.query(TutorSession)
        .filter_by(id=session_id, user_id=user.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    old = (
        db.query(TutorTurn)
        .filter_by(session_id=session_id, request_id=body.request_id)
        .first()
    )
    if old:
        submitted = (old.checkpoint or {}).get("grade_input", {})
        if (
            submitted.get("exercise_id") != body.exercise_id
            or submitted.get("answer") != body.answer
        ):
            raise HTTPException(409, "request_id 已用于另一份答案。")
        return with_events(db, old)
    active = (
        db.query(TutorTurn)
        .filter(TutorTurn.session_id == session_id, TutorTurn.status.in_(store.ACTIVE))
        .first()
    )
    if active and active.status == "waiting_input":
        active_cp = dict(active.checkpoint or {})
        active_agent = dict(active_cp.get("agent", {}))
        capability = get_capability(active_agent.get("capability", active_agent.get("profile", "tutor")))
        if not capability.ready_to_finish(active_cp) or (active.pending_action or {}).get("kind") == "execution_review":
            raise HTTPException(409, "请先处理当前解题或中断核对，或停止当前轮次，再提交练习答案。")
        active.status, active.pending_action = "completed", None
        active_agent["result"] = capability.result(active_cp, "completed")
        active_cp["agent"] = active_agent
        active.checkpoint = active_cp
        value = store.serialize_turn(active)
        value["last_seq"] += 1
        store.add_event(db, active, "done", {"turn": value})
    elif active:
        raise HTTPException(409, "请先完成当前回复或处理路径变更预览。")
    session.node_id, session.mode = (
        node.id,
        "review" if session.mode == "review" else "study",
    )
    db.commit()
    seed = {
        "grade_input": {
            "exercise_id": body.exercise_id,
            "answer": body.answer,
            "request_id": str(uuid5(NAMESPACE_URL, session_id + ":" + body.request_id)),
        }
    }
    content = "回答练习：" + exercise.prompt[:150] + "\n\n我的回答：" + body.answer
    return with_events(db, admit_turn(db, session, content, body.request_id, seed))


@router.get("/tutor/turns/{turn_id}")
def get_turn(turn_id: str, user=AUTH, db=DB):
    return with_events(db, owned(db, TutorTurn, turn_id, user.id))


@router.post("/tutor/turns/{turn_id}/respond")
async def respond(turn_id: str, body: Respond, user=AUTH, db=DB):
    owned(db, TutorTurn, turn_id, user.id)
    store.write_lock(db)
    turn = (
        db.query(TutorTurn)
        .filter_by(id=turn_id, user_id=user.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    pending = turn.pending_action
    if turn.status not in {"waiting_input", "waiting_confirmation"} or not pending:
        raise HTTPException(409, "当前轮次没有待处理的提问或变更。")
    cp = dict(turn.checkpoint)
    if pending["kind"] in {"path_change", "question_repair"}:
        if body.approved is None or body.action_id != pending["action_id"]:
            raise HTTPException(422, "请明确接受或拒绝当前变更预览。")
        if not body.approved:
            result = {"approved": False, "message": "用户拒绝变更，原有记录保持不变。"}
        elif pending["kind"] == "question_repair":
            from backend.assessment_repair import apply_repair

            result = await apply_repair(db, user.id, pending)
            store.add_event(db, turn, "question_repaired", result)
        else:
            result = paths.apply(db, user.id, pending)
        session = db.get(TutorSession, turn.session_id)
        if body.approved and session and session.node_id:
            node = db.get(Node, session.node_id)
            if not node or node.retired:
                next_node = (
                    db.query(Node)
                    .filter_by(
                        course_id=session.course_id, user_id=user.id, retired=False
                    )
                    .filter(Node.status.in_(["available", "learning"]))
                    .order_by(Node.position)
                    .first()
                )
                session.node_id = next_node.id if next_node else None
        store.add_event(
            db,
            turn,
            "user_response",
            {
                "content": "接受这些变更" if body.approved else "拒绝变更",
                "origin": "confirmation",
                "output_offset": len(turn.output),
            },
        )
    else:
        if not body.content or not body.content.strip():
            raise HTTPException(422, "请填写回答。")
        result = {"answer": body.content}
        store.add_event(
            db,
            turn,
            "user_response",
            {"content": body.content, "origin": "user_input", "output_offset": len(turn.output)},
        )
    cp["resume_result"] = result
    turn.checkpoint, turn.pending_action = cp, None
    turn.status, turn.worker_token, turn.lease_until = "queued", None, None
    store.add_event(
        db, turn, "status", {"status": "queued", "message": "收到，继续处理"}
    )
    db.commit()
    return with_events(db, turn)


@router.post("/tutor/turns/{turn_id}/cancel")
def cancel(turn_id: str, user=AUTH, db=DB):
    owned(db, TutorTurn, turn_id, user.id)
    store.write_lock(db)
    turn = (
        db.query(TutorTurn)
        .filter_by(id=turn_id, user_id=user.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if turn.status not in store.TERMINAL:
        turn.status, turn.worker_token, turn.lease_until, turn.pending_action = (
            "cancelled",
            None,
            None,
            None,
        )
        cp = dict(turn.checkpoint or {})
        agent = dict(cp.get("agent", {}))
        agent["result"] = get_capability(agent.get("capability", agent.get("profile", "tutor"))).result(cp, "cancelled")
        cp["agent"] = agent
        turn.checkpoint = cp
        value = store.serialize_turn(turn)
        value["last_seq"] += 1
        store.add_event(db, turn, "done", {"turn": value})
        db.commit()
    return with_events(db, turn)


@router.get("/tutor/turns/{turn_id}/events")
async def events(
    turn_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    user=AUTH,
    db=DB,
):
    owned(db, TutorTurn, turn_id, user.id)
    db.rollback()

    async def stream():
        cursor = after_seq
        last_ping = 0
        while not await request.is_disconnected():
            with SessionLocal() as session:
                turn = (
                    session.query(TutorTurn)
                    .filter_by(id=turn_id, user_id=user.id)
                    .first()
                )
                if not turn:
                    return
                rows = (
                    session.query(TutorEvent)
                    .filter(TutorEvent.turn_id == turn_id, TutorEvent.seq > cursor)
                    .order_by(TutorEvent.seq)
                    .limit(200)
                    .all()
                )
                status, last_seq = turn.status, turn.last_seq
                frames = [(row.seq, row.type, row.payload) for row in rows]
            for seq, kind, payload in frames:
                cursor = seq
                value = json.dumps(
                    {"seq": seq, "type": kind, "payload": payload}, ensure_ascii=False
                )
                yield f"id: {seq}\nevent: {kind}\ndata: {value}\n\n"
            if cursor >= last_seq and status not in {"queued", "running"}:
                return
            if last_ping >= 25:
                yield ": keepalive\n\n"
                last_ping = 0
            last_ping += 1
            await asyncio.sleep(0.3 if not frames else 0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


async def import_file(
    course_id, file, user, db, *, source_id=None, expected_version=None
):
    settings = get_settings()
    course = owned(db, Course, course_id, user.id)
    filename = Path(file.filename or "document").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".docx"}:
        await file.close()
        raise HTTPException(422, "支持 PDF、TXT、Markdown 和 DOCX 文件。")
    contents = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if not contents or len(contents) > settings.max_upload_bytes:
        raise HTTPException(413, "文件为空或超过上传大小限制。")
    directory = settings.data_dir / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (str(uuid4()) + suffix)
    target.write_bytes(contents)
    task = Task(
        user_id=user.id,
        course_id=course.id,
        kind="ingest",
        payload={
            "upload_path": str(target.resolve()),
            "filename": filename,
            **(
                {"source_id": source_id, "expected_version": expected_version}
                if source_id
                else {}
            ),
        },
        message="等待解析并导入资料",
    )
    db.add(task)
    db.commit()
    from backend.workflows import dispatch

    dispatch(task.id)
    return task_json(db, task)


FILE_UPLOAD = File(...)


@router.post("/courses/{course_id}/imports")
async def import_course_file(
    course_id: str, file: UploadFile = FILE_UPLOAD, user=AUTH, db=DB
):
    return await import_file(course_id, file, user, db)


@router.post("/tutor/imports")
async def import_new_course_file(file: UploadFile = FILE_UPLOAD, user=AUTH, db=DB):
    name = Path(file.filename or "资料学习").stem[:100]
    course = Course(
        user_id=user.id, title=name, goal="基于上传资料学习：" + name, status="draft"
    )
    db.add(course)
    db.flush()
    try:
        return await import_file(course.id, file, user, db)
    except Exception:
        db.rollback()
        raise
