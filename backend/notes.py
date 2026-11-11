"""Small, owned Markdown notebook. Callers own commit/cancellation boundaries."""

import copy
import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.models.domain import Course, Source, now
from backend.models.notebook import NotebookNote
from backend.models.tutor import TutorSession, TutorTurn


def _owned(db, model, identifier, user_id):
    row = db.query(model).filter_by(id=identifier, user_id=user_id).first()
    if row is None:
        raise HTTPException(404, "资源不存在。")
    return row


def _text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(422, f"{label}不能为空，且不得超过{maximum}字符。")
    return value.strip()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _request_key(value):
    return _text(value, "request_id", 120) if value is not None else None


def _dto(row):
    return {key: copy.deepcopy(getattr(row, key)) for key in (
        "id", "course_id", "title", "content", "version", "sources", "created_at", "updated_at"
    )}


def _authorize_note(db, user_id, note_id):
    note = _owned(db, NotebookNote, note_id, user_id)
    if note.course_id:
        _owned(db, Course, note.course_id, user_id)
    return note


def _sources(db, user_id, course_id, source_ids):
    if source_ids is None:
        source_ids = []
    if (not isinstance(source_ids, list) or len(source_ids) > 40
            or any(not isinstance(key, str) or not key.strip() for key in source_ids)):
        raise HTTPException(422, "source_ids须为最多40个资料ID。")
    citations = []
    for identifier in dict.fromkeys(source_ids):
        source = _owned(db, Source, identifier, user_id)
        _owned(db, Course, source.course_id, user_id)
        if course_id and source.course_id != course_id:
            raise HTTPException(404, "资料不属于当前课程。")
        citations.append({"source_id": source.id, "title": source.title, "url": source.url,
                          "source_version": getattr(source, "version", 1) or 1})
    return citations


def _save(db, user_id, title, content, course_id, sources, request_id, origin_turn_id=None, request_spec=None):
    title, content = _text(title, "标题", 255), _text(content, "笔记", 200000)
    key = _request_key(request_id)
    if course_id:
        _owned(db, Course, course_id, user_id)
    spec = {"title": title, "content": content, "course_id": course_id,
            "sources": sources, "origin_turn_id": origin_turn_id}
    fingerprint = _digest(request_spec if request_spec is not None else spec)
    if key:
        existing = db.query(NotebookNote).filter_by(user_id=user_id, request_id=key).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise HTTPException(409, "request_id已用于另一份笔记。")
            return _dto(_authorize_note(db, user_id, existing.id))
    row = NotebookNote(user_id=user_id, title=title, content=content, course_id=course_id,
                       sources=copy.deepcopy(sources), origin_turn_id=origin_turn_id,
                       request_id=key, request_fingerprint=fingerprint)
    # SQLite's legacy driver does not BEGIN for reads. A bare SAVEPOINT would
    # otherwise commit on release, escaping the caller's rollback/cancellation.
    connection = db.connection()
    if db.bind.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.query(NotebookNote).filter_by(user_id=user_id, request_id=key).first() if key else None
        if existing is None or existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "笔记正在更新，请重试。") from None
        return _dto(_authorize_note(db, user_id, existing.id))
    return _dto(row)


def list_notes(db, user_id, course_id=None):
    query = db.query(NotebookNote).filter_by(user_id=user_id)
    if course_id:
        _owned(db, Course, course_id, user_id)
        query = query.filter_by(course_id=course_id)
    return [_dto(row) for row in query.order_by(NotebookNote.updated_at.desc(), NotebookNote.id).all()]


def get_note(db, user_id, note_id):
    return _dto(_authorize_note(db, user_id, note_id))


def create_note(db, user_id, title, content, course_id=None, source_ids=None, request_id=None):
    citations = _sources(db, user_id, course_id, source_ids)
    spec = {"operation": "create", "title": title, "content": content, "course_id": course_id,
            "source_ids": sorted(set(source_ids or []))}
    return _save(db, user_id, title, content, course_id, citations, request_id, request_spec=spec)


def save_from_turn(db, user_id, turn_id, title=None, request_id=None):
    turn = _owned(db, TutorTurn, turn_id, user_id)
    session = _owned(db, TutorSession, turn.session_id, user_id)
    if turn.status != "completed" or not turn.output.strip():
        raise HTTPException(409, "请等待回答完成后再保存笔记。")
    if session.course_id:
        _owned(db, Course, session.course_id, user_id)
    # Citations are server checkpoints, never client-provided text or IDs.
    citations = copy.deepcopy((turn.checkpoint or {}).get("citations", []))
    if not isinstance(citations, list) or len(citations) > 80:
        raise HTTPException(409, "本次回答引用无效，请重试。")
    for citation in citations:
        if not isinstance(citation, dict):
            raise HTTPException(409, "本次回答引用无效。")
        if citation.get("source_id"):
            _sources(db, user_id, session.course_id, [citation["source_id"]])
    key = request_id or f"turn-note:{turn.id}"
    return _save(db, user_id, title or session.title or "学习笔记", turn.output,
                 session.course_id, citations, key, origin_turn_id=turn.id,
                 request_spec={"operation": "from_turn", "turn_id": turn.id, "title": title})


def update_note(db, user_id, note_id, expected_version, title=None, content=None):
    row = _authorize_note(db, user_id, note_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
        raise HTTPException(422, "expected_version须为正整数。")
    if row.version != expected_version:
        raise HTTPException(409, "笔记已在其他位置更新，请重新打开后编辑。")
    values = {}
    if title is not None:
        values["title"] = _text(title, "标题", 255)
    if content is not None:
        values["content"] = _text(content, "笔记", 200000)
    if not values:
        raise HTTPException(422, "请提供标题或笔记正文。")
    if all(getattr(row, key) == value for key, value in values.items()):
        return _dto(row)
    values.update(version=expected_version + 1, updated_at=now())
    # Conditional update also catches simultaneous requests with stale identity maps.
    result = db.execute(update(NotebookNote).where(
        NotebookNote.id == note_id, NotebookNote.user_id == user_id,
        NotebookNote.version == expected_version,
    ).values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "笔记已在其他位置更新，请重新打开后编辑。")
    db.flush()
    db.refresh(row)
    return _dto(row)


def export_note(db, user_id, note_id):
    note = get_note(db, user_id, note_id)
    markdown = f"# {note['title']}\n\n{note['content']}\n"
    if note["sources"]:
        markdown += "\n## 引用资料\n\n"
        for index, source in enumerate(note["sources"], 1):
            label = str(source.get("title") or source.get("source_id") or "来源").replace("\n", " ")
            url = str(source.get("url") or "")
            page = source.get("page_start") or source.get("page")
            suffix = f" · 第{page}页" if page else ""
            version = source.get("source_version")
            suffix += f" · 版本{version}" if version else ""
            markdown += f"{index}. {label}{suffix}" + (f" — {url}" if url else "") + "\n"
    filename = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", note["title"], flags=re.UNICODE).strip("._")[:100] or "Atlas-note"
    return filename + ".md", markdown
