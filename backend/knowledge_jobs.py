"""Schedule incremental indexes without blocking access to original materials."""

from datetime import UTC, datetime, timedelta
import hashlib
import json

from backend.database import SessionLocal
from backend.indexing import embedding_available, embedding_signature
from backend.models.domain import Course, Source, Task
from backend.models.library import SourceRevision

AUTO_GRAPH_MAX_CHUNKS = 40
AUTO_GRAPH_COOLDOWN = timedelta(hours=1)


def new_vector_task(source, *, automatic=False):
    return Task(
        user_id=source.user_id, course_id=source.course_id, kind="reindex",
        payload={
            "source_id": source.id, "expected_version": source.version,
            "embedding_signature": embedding_signature(),
            "previous_index": [source.embedding_signature, source.embedding_dimension],
            "automatic": automatic,
        },
        message="等待构建资料向量" if automatic else "等待重建资料索引",
    )


def pending_pdf(revision):
    return (revision and revision.page_index is None and revision.file_path
            and (revision.filename or "").lower().endswith(".pdf"))


def needs_vectors(source):
    return bool(source.chunk_count and embedding_available() and (
        source.embedding_signature != embedding_signature() or not source.embedding_dimension
    ))


def enqueue_source_indexes(db, course, source, revision):
    """Stage jobs in the same transaction as ingestion, with the course row locked."""
    from backend.knowledge import engine_requirement

    if course.knowledge_engine != "auto":
        return []
    jobs = []
    existing = db.query(Task).filter(
        Task.user_id == source.user_id, Task.course_id == source.course_id,
        Task.payload["source_id"].as_string() == source.id,
        Task.payload["expected_version"].as_integer() == source.version,
    )
    if pending_pdf(revision) and not engine_requirement("pageindex") and not existing.filter(
        Task.kind == "knowledge_page",
    ).first():
        jobs.append(Task(
            user_id=source.user_id, course_id=source.course_id, kind="knowledge_page",
            payload={"source_id": source.id, "expected_version": source.version,
                     "content_hash": revision.content_hash},
            message="等待建立 PDF 页级索引",
        ))
    if needs_vectors(source) and not existing.filter(
        Task.kind == "reindex", Task.payload["embedding_signature"].as_string() == embedding_signature(),
    ).first():
        jobs.append(new_vector_task(source, automatic=True))
    db.add_all(jobs)
    return jobs


def dispatch_indexes(jobs):
    from backend.workflows import dispatch

    for task in jobs:
        dispatch(task.id)


def queue_missing_indexes(user_id, course_id, source_ids):
    """Backfill older files or vectors when first needed in an automatic course."""
    from backend.tutor.store import write_lock

    if not source_ids:
        return
    with SessionLocal() as db:
        write_lock(db)
        course = db.query(Course).filter_by(id=course_id, user_id=user_id).with_for_update().first()
        if not course or course.knowledge_engine != "auto":
            return
        jobs = []
        for source in db.query(Source).filter(
            Source.user_id == user_id, Source.course_id == course_id, Source.id.in_(source_ids),
        ):
            revision = db.query(SourceRevision).filter_by(
                user_id=user_id, source_id=source.id, version=source.version,
            ).first()
            jobs.extend(enqueue_source_indexes(db, course, source, revision))
        db.commit()
        dispatch_indexes(jobs)


def auto_graph_key(sources):
    from backend.knowledge import source_manifest

    payload = [embedding_signature(), source_manifest(sources)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def queue_graph(user_id, course_id):
    """One automatic graph attempt per corpus, with a course-wide cooldown."""
    from backend.connections import resolve_model_config
    from backend.knowledge import engine_requirement, graph_ready, sources_for
    from backend.tutor.store import write_lock

    if engine_requirement("lightrag") or not resolve_model_config(user_id).configured:
        return False
    with SessionLocal() as db:
        write_lock(db)
        course = db.query(Course).filter_by(id=course_id, user_id=user_id).with_for_update().first()
        if not course or course.knowledge_engine != "auto":
            return False
        sources = sources_for(db, user_id, course_id).all()
        if sum(bool(source.chunk_count) for source in sources) < 2 or sum(
            source.chunk_count for source in sources
        ) > AUTO_GRAPH_MAX_CHUNKS:
            return False
        index = course.knowledge_index or {}
        if graph_ready(course, index.get("auto_graph", {}), sources):
            return False
        key = auto_graph_key(sources)
        previous = db.query(Task).filter(
            Task.user_id == user_id, Task.course_id == course_id, Task.kind == "knowledge_index",
            Task.payload["purpose"].as_string() == "auto_graph",
        )
        if previous.filter(Task.status.in_(["queued", "running"])).first():
            return True
        if previous.filter(Task.payload["request_key"].as_string() == key).first() or previous.filter(
            Task.created_at >= (datetime.now(UTC) - AUTO_GRAPH_COOLDOWN).isoformat(),
        ).first():
            return False
        job = Task(
            user_id=user_id, course_id=course_id, kind="knowledge_index",
            payload={"engine": "lightrag", "purpose": "auto_graph", "request_key": key,
                     "previous": index.get("generation")},
            message="等待补建课程概念图谱",
        )
        db.add(job)
        db.commit()
        dispatch_indexes([job])
        return True
