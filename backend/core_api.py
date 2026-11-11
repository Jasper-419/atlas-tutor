"""Small desktop-facing APIs for evidence, teaching and learning notes."""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from backend import learning, library, notes, teaching
from backend.database import get_db
from backend.indexing import embedding_available, embedding_signature, index_state
from backend.models.domain import Node, Source, Task
from backend.models.tutor import TutorSession
from backend.retrieval import prepare_source
from backend.security import current_user
from backend.serializers import source_json, task_json
from backend.tutor.api import import_file
from backend.tutor.store import write_lock
from backend.tutor.tools import owned

router = APIRouter(prefix="/api")
DB, AUTH = Depends(get_db), Depends(current_user)
UPLOAD, EXPECTED_VERSION = File(...), Form(..., ge=1)


class SourceUpdate(BaseModel):
    content: str = Field(min_length=12, max_length=400000)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    expected_version: int = Field(ge=1)


class ReindexSource(BaseModel):
    expected_version: int = Field(ge=1)


class Feedback(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    effect: Literal["helped", "not_helped", "unknown"]
    strategy: str = Field(default="", max_length=500)
    request_id: str = Field(min_length=1, max_length=120)


class Defer(BaseModel):
    reason: str = Field(default="", max_length=2000)
    days: int = Field(default=1, ge=1, le=30)


class CreateNote(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100000)
    course_id: str | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    request_id: str | None = Field(default=None, max_length=120)


class EditNote(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    expected_version: int = Field(ge=1)


class TurnNote(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)


@router.get("/sources/{source_id}")
def read_source(
    source_id: str, version: int | None = Query(default=None, ge=1), user=AUTH, db=DB
):
    result = library.source_detail(db, user.id, source_id, version)
    result.pop("_file_path", None)
    if result["version"] == result["current_version"]:
        result["index"] = index_state(db, owned(db, Source, source_id, user.id))
    return result


@router.get("/sources/{source_id}/download")
def download_source(
    source_id: str, version: int | None = Query(default=None, ge=1), user=AUTH, db=DB
):
    result = library.source_detail(db, user.id, source_id, version)
    path = library.download_path(result.pop("_file_path", None))
    if path:
        return FileResponse(path, filename=result.get("filename") or path.name)
    filename = result["title"][:120] + ".md"
    return Response(
        result["content"],
        media_type="text/markdown",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)
        },
    )


@router.put("/sources/{source_id}")
async def update_source(source_id: str, body: SourceUpdate, user=AUTH, db=DB):
    source = owned(db, Source, source_id, user.id)
    prepared = await prepare_source(body.content)
    write_lock(db)
    source = owned(db, Source, source_id, user.id)
    result = library.replace_index(
        db,
        source,
        body.content,
        prepared,
        body.title,
        expected_version=body.expected_version,
    )
    db.commit()
    return {**source_json(result), "index": index_state(db, result)}


@router.post("/sources/{source_id}/reindex")
def reindex_source(source_id: str, body: ReindexSource, user=AUTH, db=DB):
    from backend.workflows import dispatch

    user_id = user.id
    write_lock(db)
    source = db.query(Source).filter_by(id=source_id, user_id=user_id).with_for_update().first()
    if not source:
        raise HTTPException(404, "资料不存在。")
    if source.version != body.expected_version:
        raise HTTPException(409, "资料已更新，请打开当前版本再重建。")
    if not embedding_available():
        raise HTTPException(409, "请先配置可用的 embedding 服务。")
    if not source.chunk_count:
        raise HTTPException(409, "资料没有可建立索引的片段。")
    active = db.query(Task).filter(
        Task.user_id == user_id, Task.course_id == source.course_id,
        Task.kind == "reindex", Task.status.in_(["queued", "running"]),
        Task.payload["source_id"].as_string() == source.id,
    ).first()
    if active:
        return task_json(db, active)
    task = Task(
        user_id=user_id, course_id=source.course_id, kind="reindex",
        payload={
            "source_id": source.id,
            "expected_version": source.version,
            "embedding_signature": embedding_signature(),
            "previous_index": [source.embedding_signature, source.embedding_dimension],
        },
        message="等待重建资料索引",
    )
    db.add(task)
    db.commit()
    dispatch(task.id)
    return task_json(db, task)


@router.post("/sources/{source_id}/replace")
async def replace_file(
    source_id: str,
    file: UploadFile = UPLOAD,
    expected_version: int = EXPECTED_VERSION,
    user=AUTH,
    db=DB,
):
    source = owned(db, Source, source_id, user.id)
    if source.version != expected_version:
        raise HTTPException(409, "资料已更新，请重新打开后再替换。")
    return await import_file(
        source.course_id,
        file,
        user,
        db,
        source_id=source_id,
        expected_version=expected_version,
    )


@router.post("/nodes/{node_id}/lesson/regenerate")
async def regenerate_lesson(node_id: str, user=AUTH, db=DB):
    node = owned(db, Node, node_id, user.id)
    if node.retired or node.status == "locked":
        raise HTTPException(409, "当前节点尚未开放学习。")
    node.lesson_stale = True
    db.commit()
    return await learning.prepare_lesson(db, user.id, node_id)


@router.get("/courses/{course_id}/teaching")
def teaching_state(course_id: str, node_id: str | None = None, user=AUTH, db=DB):
    return teaching.get_teaching_state(db, user.id, course_id, node_id)


@router.post("/tutor/sessions/{session_id}/feedback")
def feedback(session_id: str, body: Feedback, user=AUTH, db=DB):
    session = owned(db, TutorSession, session_id, user.id)
    if not session.course_id:
        raise HTTPException(409, "请先选择课程。")
    state = teaching.get_teaching_state(db, user.id, session.course_id, session.node_id)
    node_id = session.node_id or state.get("node_id")
    if not node_id:
        raise HTTPException(409, "课程尚无可学习节点。")
    result = teaching.record_feedback(
        db, user.id, node_id, body.content, body.effect, body.strategy, body.request_id
    )
    db.commit()
    return result


@router.post("/nodes/{node_id}/defer")
def defer_node(node_id: str, body: Defer, user=AUTH, db=DB):
    result = teaching.defer_node(db, user.id, node_id, body.reason, body.days)
    db.commit()
    return result


@router.get("/notes")
def list_notes(course_id: str | None = None, user=AUTH, db=DB):
    return notes.list_notes(db, user.id, course_id)


@router.post("/notes")
def create_note(body: CreateNote, user=AUTH, db=DB):
    result = notes.create_note(
        db,
        user.id,
        body.title,
        body.content,
        body.course_id,
        body.source_ids,
        body.request_id,
    )
    db.commit()
    return result


@router.get("/notes/{note_id}")
def read_note(note_id: str, user=AUTH, db=DB):
    return notes.get_note(db, user.id, note_id)


@router.patch("/notes/{note_id}")
def update_note(note_id: str, body: EditNote, user=AUTH, db=DB):
    result = notes.update_note(
        db, user.id, note_id, body.expected_version, body.title, body.content
    )
    db.commit()
    return result


@router.post("/tutor/turns/{turn_id}/note")
def note_from_turn(turn_id: str, body: TurnNote, user=AUTH, db=DB):
    result = notes.save_from_turn(db, user.id, turn_id, body.title)
    db.commit()
    return result


@router.get("/notes/{note_id}/export")
def export_note(note_id: str, user=AUTH, db=DB):
    filename, content = notes.export_note(db, user.id, note_id)
    return Response(
        content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)
        },
    )
