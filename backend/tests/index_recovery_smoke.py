"""Exercise real index tasks against temporary SQLite with fixture embeddings."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="atlas-index-recovery-") as folder:
        os.environ.update(
            PYTHON_DOTENV_DISABLED="1",
            ATLAS_DATA_DIR=folder,
            DATABASE_URL="sqlite:///" + str(Path(folder) / "atlas.db"),
            ATLAS_CHECKPOINT_PATH=str(Path(folder) / "checkpoints.db"),
            CHECKPOINT_DATABASE_URL="",
            ATLAS_CREDENTIALS_KEY="",
            WORKER_MODE="disabled",
            EMBEDDING_MODEL="fixture-a",
            EMBEDDING_API_KEY="fixture-only",
        )
        from fastapi.testclient import TestClient
        from backend.config import get_settings
        from backend.database import SessionLocal
        from backend.indexing import BATCH_SIZE, embedding_signature
        from backend.library import replace_index
        from backend.llm import ModelError
        from backend.main import app
        from backend.models import Chunk, IndexBatch, Source, Task
        from backend.retrieval_agent import read_material
        from backend.workflows import claim_task, run_task

        def ok(response, status=200):
            assert response.status_code == status, (response.status_code, response.text[:300])
            return response.json()

        def snapshot(source_id):
            with SessionLocal() as db:
                source = db.get(Source, source_id)
                chunks = db.query(Chunk).filter_by(source_id=source_id).order_by(Chunk.chunk_index).all()
                return source.version, source.embedding_signature, [(row.id, row.content, row.embedding) for row in chunks]

        def task_state(task_id):
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                batches = db.query(IndexBatch).filter_by(task_id=task_id).count()
                return task.status, task.result, batches

        async def old_vectors(texts):
            return [[1.0, 0.0] for _ in texts]

        with TestClient(app) as owner, TestClient(app) as outsider:
            for client, name in [(owner, "owner"), (outsider, "outsider")]:
                ok(client.post("/api/auth/register", json={
                    "email": name + "@index-fixture.invalid", "password": "IndexFixture123!", "full_name": name,
                }))
            template = ok(owner.get("/api/templates"))[0]
            course = ok(owner.post(f"/api/templates/{template['id']}/enroll"))
            original = "\n".join(f"chapter {n}: " + ("atlas recovery " * 60) for n in range(60))
            source = ok(owner.post(f"/api/courses/{course['id']}/sources/text", json={
                "title": "Index recovery fixture", "content": original,
            }))
            source_id = source["id"]
            url = f"/api/sources/{source_id}"
            # Automatic upload is searchable before its queued embedding work runs.
            assert ok(owner.get(url))["index"]["state"] == "lexical"
            initial_task = claim_task()
            assert initial_task
            with patch("backend.indexing.embeddings", old_vectors):
                asyncio.run(run_task(initial_task))
            initial = snapshot(source_id)
            assert BATCH_SIZE < len(initial[2]) <= 2 * BATCH_SIZE
            assert initial[1] == embedding_signature()
            settings = get_settings()
            settings.embedding_model = "fixture-b"  # same dimensionality, different identity
            assert ok(owner.get(url))["index"]["state"] == "embedding_model_changed"
            request = {"expected_version": source["version"]}
            ok(outsider.post(url + "/reindex", json=request), 404)
            ok(owner.post(url + "/reindex", json={"expected_version": 2}), 409)
            task = ok(owner.post(url + "/reindex", json=request))
            task_id = task["id"]
            assert ok(owner.post(url + "/reindex", json=request))["id"] == task_id
            assert claim_task(task_id) == task_id
            calls = []

            async def interrupted(texts):
                calls.append(len(texts))
                if len(calls) == 2:
                    raise asyncio.CancelledError()
                return [[0.0, 1.0] for _ in texts]

            with patch("backend.indexing.embeddings", interrupted):
                try:
                    asyncio.run(run_task(task_id))
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("Expected interrupted worker")
            assert task_state(task_id) == ("running", None, 1)
            assert snapshot(source_id) == initial
            with SessionLocal() as db:
                db.get(Task, task_id).lease_until = "2000-01-01T00:00:00+00:00"
                db.commit()
            assert claim_task(task_id) == task_id
            failed_calls = []

            async def unavailable(texts):
                failed_calls.append(len(texts))
                raise ModelError("fixture provider unavailable")

            with patch("backend.indexing.embeddings", unavailable):
                asyncio.run(run_task(task_id))
            assert failed_calls == [len(initial[2]) - BATCH_SIZE]
            assert task_state(task_id) == ("failed", None, 1)
            assert snapshot(source_id) == initial
            ok(owner.post(f"/api/tasks/{task_id}/retry"))
            assert claim_task(task_id) == task_id
            resumed_calls = []

            async def new_vectors(texts):
                resumed_calls.append(len(texts))
                return [[0.0, 1.0] for _ in texts]

            with patch("backend.indexing.embeddings", new_vectors):
                asyncio.run(run_task(task_id))
            status, result, batches = task_state(task_id)
            assert status == "succeeded" and result["reused_batches"] == 1 and batches == 0
            assert resumed_calls == failed_calls
            rebuilt = snapshot(source_id)
            assert rebuilt[0] == initial[0] and rebuilt[1] == embedding_signature()
            assert [row[:2] for row in rebuilt[2]] == [row[:2] for row in initial[2]]
            assert all(row[2] == [0.0, 1.0] for row in rebuilt[2])
            assert ok(owner.get(url))["index"]["state"] == "ready"

            stale_id = ok(owner.post(url + "/reindex", json=request))["id"]
            assert claim_task(stale_id) == stale_id
            new_text = "The newer source version must remain active."

            async def edit_during_build(texts):
                with SessionLocal() as db:
                    row = db.get(Source, source_id)
                    if row.version == 1:
                        replace_index(db, row, new_text, ([new_text], []), expected_version=1)
                        db.commit()
                return await new_vectors(texts)

            with patch("backend.indexing.embeddings", edit_during_build):
                asyncio.run(run_task(stale_id))
            assert task_state(stale_id)[0] == "failed"
            assert snapshot(source_id)[0:2] == (2, None)
            with SessionLocal() as db:
                row = db.get(Source, source_id)
                old = read_material(db, row.user_id, row.course_id, source_id, version=1, max_chars=200)
                assert old["content"] == original[:200]

        print("PASS: model identity, owned reindex, expired lease and retry reuse, atomic publication, and unchanged historical evidence")


if __name__ == "__main__":
    main()
