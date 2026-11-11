"""Versioned source evidence and authenticated original-document access."""

import hashlib
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from backend.config import get_settings
from backend.models.domain import Chunk, Node, Source, Task
from backend.models.library import SourceRevision


def content_hash(content):
    return hashlib.sha256(content.strip().encode()).hexdigest()


def page_sections(content):
    markers = list(re.finditer(r"\[第\s*(\d+)\s*页\]", content))
    return [
        {
            "page": int(marker[1]),
            "text": content[
                marker.end() : markers[index + 1].start()
                if index + 1 < len(markers)
                else len(content)
            ].strip(),
        }
        for index, marker in enumerate(markers)
    ]


def chunk_locator(content, piece, start=0):
    offset = content.find(piece, max(0, start - 220))
    if offset < 0:
        offset = max(0, start)
    end = offset + len(piece)
    before = list(re.finditer(r"\[第\s*(\d+)\s*页\]", content[: offset + 1]))
    inside = list(re.finditer(r"\[第\s*(\d+)\s*页\]", content[offset:end]))
    first = int(before[-1][1]) if before else int(inside[0][1]) if inside else None
    last = int(inside[-1][1]) if inside else first
    headings = list(re.finditer(r"(?m)^#{1,5}\s+([^\n]+)", content[:end]))
    return {
        "page_start": first,
        "page_end": last,
        "section": headings[-1][1][:300] if headings else None,
    }, end


def merge_chunks(chunks):
    result = ""
    for chunk in chunks:
        body = chunk.content
        overlap = next(
            (
                n
                for n in range(min(220, len(result), len(body)), 19, -1)
                if result.endswith(body[:n])
            ),
            0,
        )
        result += ("\n" if result and not overlap else "") + body[overlap:]
    return result


def current_source_hash(db, source):
    if source.content_hash:
        return source.content_hash
    return content_hash(
        merge_chunks(
            db.query(Chunk)
            .filter_by(source_id=source.id, user_id=source.user_id)
            .order_by(Chunk.chunk_index)
        )
    )


def original_file(db, source):
    tasks = (
        db.query(Task)
        .filter_by(
            user_id=source.user_id,
            course_id=source.course_id,
            kind="ingest",
            status="succeeded",
        )
        .order_by(Task.created_at.desc())
        .all()
    )
    for task in tasks:
        result = task.result or {}
        if source.id == result.get("source_id") or source.id in result.get(
            "source_ids", []
        ):
            return (task.payload or {}).get("upload_path"), (task.payload or {}).get(
                "filename"
            )
    return None, None


def ensure_revision(db, source, content=None, file_path=None, filename=None):
    revision = (
        db.query(SourceRevision)
        .filter_by(source_id=source.id, version=source.version or 1)
        .first()
    )
    if not revision:
        if content is None:
            content = merge_chunks(
                db.query(Chunk)
                .filter_by(source_id=source.id, user_id=source.user_id)
                .order_by(Chunk.chunk_index)
            )
        if file_path is None and (source.version or 1) == 1:
            file_path, filename = original_file(db, source)
        revision = SourceRevision(
            id=str(uuid5(NAMESPACE_URL, source.id + ":" + str(source.version or 1))),
            user_id=source.user_id,
            source_id=source.id,
            version=source.version or 1,
            title=source.title,
            content=content,
            content_hash=content_hash(content),
            url=source.url,
            kind=source.kind,
            pages=page_sections(content),
            file_path=file_path,
            filename=filename,
        )
        db.add(revision)
        source.content_hash = revision.content_hash
        db.flush()
    elif file_path:
        if content is not None and content_hash(content) != revision.content_hash:
            raise HTTPException(409, "原附件与该资料版本正文不一致，未绑定附件。")
        # Original ingestion binds the spool in the same transaction as indexing.
        revision.file_path, revision.filename = file_path, filename
    return revision


def mark_lessons_stale(db, source):
    for node in db.query(Node).filter_by(
        user_id=source.user_id, course_id=source.course_id
    ):
        references = node.lesson_citations or []
        if source.id in (node.lesson_source_versions or {}) or any(
            ref.get("source_id") == source.id for ref in references
        ):
            node.lesson_stale = True


def replace_index(
    db,
    source,
    content,
    prepared,
    title=None,
    file_path=None,
    filename=None,
    expected_version=None,
):
    # Caller serializes the write and has done all embedding I/O beforehand.
    source = (
        db.query(Source)
        .filter_by(id=source.id, user_id=source.user_id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if expected_version is not None and source.version != expected_version:
        raise HTTPException(409, "资料已更新，请重新打开后再修改。")
    old = ensure_revision(db, source)
    new_hash = content_hash(content)
    if new_hash == old.content_hash and (title is None or title == source.title):
        return source
    pieces, vectors = prepared
    source.version += 1
    source.content_hash = new_hash
    if title:
        source.title = title[:255]
    db.query(Chunk).filter_by(source_id=source.id, user_id=source.user_id).delete(
        synchronize_session=False
    )
    offset = 0
    for index, piece in enumerate(pieces):
        locator, offset = chunk_locator(content, piece, offset)
        db.add(
            Chunk(
                user_id=source.user_id,
                source_id=source.id,
                course_id=source.course_id,
                chunk_index=index,
                content=piece,
                embedding=vectors[index] if vectors else None,
                **locator,
            )
        )
    source.chunk_count = len(pieces)
    db.flush()
    ensure_revision(db, source, content, file_path=file_path, filename=filename)
    mark_lessons_stale(db, source)
    return source


def source_detail(db, user_id, source_id, version=None):
    source = db.query(Source).filter_by(id=source_id, user_id=user_id).first()
    if not source:
        raise HTTPException(404, "资料不存在。")
    target = version or source.version
    revision = (
        db.query(SourceRevision)
        .filter_by(source_id=source.id, user_id=user_id, version=target)
        .first()
    )
    if not revision and target == source.version:
        content = merge_chunks(
            db.query(Chunk)
            .filter_by(source_id=source.id, user_id=user_id)
            .order_by(Chunk.chunk_index)
        )
        path, filename = original_file(db, source)
        return {
            "id": source.id,
            "course_id": source.course_id,
            "title": source.title,
            "content": content,
            "version": target,
            "current_version": source.version,
            "url": source.url,
            "kind": source.kind,
            "filename": filename,
            "pages": page_sections(content),
            "_file_path": path,
        }
    if not revision:
        raise HTTPException(404, "该资料版本不存在。")
    return {
        "id": source.id,
        "course_id": source.course_id,
        "title": revision.title,
        "content": revision.content,
        "version": revision.version,
        "current_version": source.version,
        "url": revision.url,
        "kind": revision.kind,
        "filename": revision.filename,
        "pages": revision.pages,
        "_file_path": revision.file_path,
    }


def download_path(value):
    if not value:
        return None
    path = Path(value).resolve()
    if (
        path.parent != (get_settings().data_dir / "uploads").resolve()
        or not path.is_file()
        or Path(value).is_symlink()
    ):
        return None
    return path
