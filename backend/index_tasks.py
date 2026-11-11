"""Durable candidate batches and atomic publication of rebuilt source vectors."""

import hashlib
import json

from backend.database import SessionLocal
from backend.indexing import build_index
from backend.llm import ModelError
from backend.models import Chunk, IndexBatch, Source, Task


class IndexCheckpoint:
    def __init__(self, task_id, run_id, source_id=None):
        self.task_id = task_id
        self.run_id = run_id
        self.source_id = source_id
        self.fingerprint = None

    def load(self, pieces, signature):
        # Exact ordered pieces bind checkpoints to both parser and chunker output.
        payload = json.dumps([signature, pieces], ensure_ascii=False, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with SessionLocal() as db:
            return dict(db.query(IndexBatch.offset, IndexBatch.vectors).filter_by(
                task_id=self.task_id, fingerprint=self.fingerprint, source_id=self.source_id,
            ).all())

    def save(self, offset, vectors, total):
        from backend.workflows import lock_owned_task

        with SessionLocal() as db:
            task = lock_owned_task(db, self.task_id, self.run_id)
            batch = db.get(IndexBatch, (task.id, offset))
            if batch is None:
                batch = IndexBatch(task_id=task.id, offset=offset)
                db.add(batch)
            batch.source_id = self.source_id
            batch.fingerprint = self.fingerprint
            batch.vectors = vectors
            done = offset + len(vectors)
            task.progress = 45 + int(42 * done / total)
            task.message = f"已建立 {done}/{total} 个资料片段的向量"
            db.commit()

    def clear(self, db):
        db.query(IndexBatch).filter_by(task_id=self.task_id).delete(synchronize_session=False)


def _chunks(db, source):
    return db.query(Chunk).filter_by(
        source_id=source.id, course_id=source.course_id, user_id=source.user_id,
    ).order_by(Chunk.chunk_index, Chunk.id).all()


async def rebuild_source_index(task_id):
    from backend.workflows import Cancelled, check_live, lock_owned_task, update_progress

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            raise Cancelled()
        run_id = task.run_id
        payload = dict(task.payload)
        scope = {"id": payload["source_id"], "user_id": task.user_id, "course_id": task.course_id}
        source = db.query(Source).filter_by(**scope).first()
        if not source or source.version != payload["expected_version"]:
            raise ModelError("资料版本已变化，请打开当前资料重新发起重建。")
        chunks = _chunks(db, source)
        if not chunks or len(chunks) != source.chunk_count:
            raise ModelError("资料片段不完整，请重新保存资料后重建。")
        snapshot = [(chunk.id, chunk.content, chunk.chunk_index) for chunk in chunks]
    check_live(task_id, run_id)
    update_progress(task_id, 45, "准备资料索引", run_id)
    checkpoint = IndexCheckpoint(task_id, run_id, scope["id"])
    prepared = await build_index(
        [content for _, content, _ in snapshot], checkpoint=checkpoint,
        expected_signature=payload["embedding_signature"],
    )
    with SessionLocal() as db:
        task = lock_owned_task(db, task_id, run_id)
        source = db.query(Source).filter_by(**scope).with_for_update().first()
        if not source or source.version != payload["expected_version"]:
            raise ModelError("资料版本已变化，请打开当前资料重新发起重建。")
        if [source.embedding_signature, source.embedding_dimension] != payload["previous_index"]:
            raise ModelError("资料索引已更新，请刷新后重新发起重建。")
        chunks = _chunks(db, source)
        if [(chunk.id, chunk.content, chunk.chunk_index) for chunk in chunks] != snapshot:
            raise ModelError("资料片段已变化，请重新发起索引重建。")
        for chunk, vector in zip(chunks, prepared.vectors, strict=True):
            chunk.embedding = vector
        prepared.bind(source)
        checkpoint.clear(db)
        task.status, task.progress = "succeeded", 100
        task.message = "资料索引已重建"
        task.error, task.lease_until, task.worker_token = None, None, None
        task.result = {
            "source_id": source.id,
            "source_ids": [source.id],
            "version": source.version,
            "chunk_count": len(chunks),
            "reused_batches": prepared.reused_batches,
        }
        db.commit()
