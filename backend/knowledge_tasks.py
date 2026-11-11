"""Publish course retrieval changes behind the durable task fence."""

import asyncio
from sqlalchemy.orm import load_only

from backend.database import SessionLocal
from backend.index_tasks import IndexCheckpoint
from backend.indexing import build_index, embedding_available, embedding_signature
from backend.knowledge import engine_requirement, source_manifest, sources_for
from backend.llm import ModelError
from backend.models.domain import Chunk, Course, Source, Task
from backend.models.library import SourceRevision


async def build_source_pages(task_id):
    from backend.knowledge_pages import build
    from backend.workflows import Cancelled, check_live, lock_owned_task, update_progress

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            raise Cancelled()
        run_id, user_id, course_id = task.run_id, task.user_id, task.course_id
        payload = task.payload
        scope = {"id": payload["source_id"], "user_id": user_id, "course_id": course_id}
        source = db.query(Source).filter_by(**scope).first()
        revision_scope = {"source_id": scope["id"], "user_id": user_id,
                          "version": payload["expected_version"], "content_hash": payload["content_hash"]}
        revision = db.query(SourceRevision).filter_by(**revision_scope).first()
        if not source or source.version != payload["expected_version"] or not revision:
            raise ModelError("资料版本已更新，旧页级索引已跳过。")
    check_live(task_id, run_id)
    update_progress(task_id, 30, "建立 PDF 页级索引", run_id)
    sections = revision.page_index
    if sections is None:
        sections = (await build({source.id: revision}, lambda: check_live(task_id, run_id),
                                allow_empty=True)).get(source.id, [])
    with SessionLocal() as db:
        task = lock_owned_task(db, task_id, run_id)
        source = db.query(Source).filter_by(**scope).with_for_update().first()
        revision = db.query(SourceRevision).filter_by(**revision_scope).first()
        current = source and source.version == payload["expected_version"] and revision
        if current:
            revision.page_index = sections
        task.status, task.progress = "succeeded", 100
        task.message = "PDF 页级索引已就绪" if current and sections else "已完成资料页级索引检查"
        task.result = {"source_id": scope["id"], "version": payload["expected_version"],
                       "page_indexed": bool(current and sections)}
        task.error, task.lease_until, task.worker_token = None, None, None
        db.commit()


async def build_llama_index(task_id, run_id, rows, sources, *, rebuild_vectors):
    from backend.knowledge_llama import bm25_index, token_text

    records = tuple(
        (chunk.id, token_text(sources[chunk.source_id].title + " " + chunk.content))
        for chunk, _, _, _ in rows
    )
    await asyncio.to_thread(bm25_index, records)
    if not embedding_available():
        return None, [], None
    signature = embedding_signature()
    missing = [chunk for chunk, _, signed, dimension in rows
               if rebuild_vectors or signed != signature or not dimension]
    if not missing:
        return None, [], signature
    checkpoint = IndexCheckpoint(task_id, run_id)
    prepared = await build_index(
        [chunk.content for chunk in missing], checkpoint=checkpoint, expected_signature=signature,
    )
    return prepared, missing, signature


async def rebuild_library(task_id):
    from backend import knowledge_graph, knowledge_pages
    from backend.knowledge_llama import MAX_CHUNKS, library_chunks
    from backend.workflows import Cancelled, check_live, update_progress

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            raise Cancelled()
        user_id, course_id, run_id = task.user_id, task.course_id, task.run_id
        course = db.query(Course).filter_by(id=course_id, user_id=user_id).first()
        if not course:
            raise Cancelled()
        mode = course.knowledge_engine
        engine = task.payload["engine"]
        automatic_graph = task.payload.get("purpose") == "auto_graph"
        previous = task.payload["previous"]
        rebuild_vectors = task.payload.get("rebuild_vectors", False)
        sources = {source.id: source for source in sources_for(db, user_id, course_id).order_by(Source.id)}
        manifest = source_manifest(sources.values())
        rows, revisions = [], {}
        if sources and engine in {"llamaindex", "lightrag"}:
            rows = library_chunks(db, list(sources.values())).options(
                load_only(Chunk.id, Chunk.source_id, Chunk.content),
            ).limit(MAX_CHUNKS + 1).all()
        elif engine == "pageindex":
            revisions = knowledge_pages.current_revisions(db, list(sources.values()))
    requirement = engine_requirement(engine)
    if requirement:
        raise ModelError(requirement)
    if automatic_graph:
        from backend.knowledge_jobs import auto_graph_key

        if mode != "auto" or auto_graph_key(sources.values()) != task.payload["request_key"]:
            raise ModelError("资料或检索模式已变化，暂缓建立自动图谱。")
    check_live(task_id, run_id)
    update_progress(task_id, 20, "准备课程检索索引", run_id)
    prepared, missing, signature = None, [], None
    index = {"generation": task_id}
    graph = None
    if engine in {"llamaindex", "lightrag"} and (
        len(rows) != sum(source.chunk_count for source in sources.values())
        or any(sources[chunk.source_id].version != version for chunk, version, _, _ in rows)
    ):
        raise ModelError("资料在读取索引时变化或超出容量，请检查资料后重建。")
    if engine == "llamaindex":
        if len(rows) > MAX_CHUNKS:
            raise ModelError(f"LlamaIndex 每个知识库最多构建 {MAX_CHUNKS} 个资料片段。")
        prepared, missing, signature = await build_llama_index(
            task_id, run_id, rows, sources, rebuild_vectors=rebuild_vectors,
        )
    elif engine == "pageindex":
        index.update(sources=manifest, sections=await knowledge_pages.build(
            revisions, lambda: check_live(task_id, run_id),
        ))
        if not index["sections"]:
            raise ModelError("请先上传带文本层的 PDF，再启用 PageIndex。")
    elif engine == "lightrag":
        if len(rows) > knowledge_graph.MAX_GRAPH_CHUNKS:
            raise ModelError(f"LightRAG 每个知识库最多构建 {knowledge_graph.MAX_GRAPH_CHUNKS} 个资料片段。")
        graph = knowledge_graph.new_workspace(user_id, course_id)

    def graph_progress(done, total):
        check_live(task_id, run_id)
        update_progress(task_id, 25 + int(60 * done / total), f"建立概念图谱 · {done}/{total} 个片段", run_id)

    try:
        if graph:
            index.update(sources=manifest, **await knowledge_graph.build(
                graph, user_id, [chunk for chunk, _, _, _ in rows], task_id, graph_progress,
            ))
            signature = index["embedding_signature"]
        old_graph, keep_graph = publish(task_id, run_id, user_id, course_id, previous, engine, index,
                                        manifest, prepared, missing, signature, automatic_graph)
    except BaseException:
        if graph:
            knowledge_graph.remove_workspace(user_id, course_id, graph.name)
        raise
    if old_graph and old_graph != keep_graph:
        knowledge_graph.remove_workspace(user_id, course_id, old_graph)


def publish(task_id, run_id, user_id, course_id, previous, engine, index,
            manifest, prepared, missing, signature, automatic_graph):
    from backend.knowledge import graph_index
    from backend.knowledge_jobs import dispatch_indexes, enqueue_source_indexes
    from backend.workflows import Cancelled, lock_owned_task

    with SessionLocal() as db:
        task = lock_owned_task(db, task_id, run_id)
        course = db.query(Course).filter_by(id=course_id, user_id=user_id).with_for_update().first()
        if not course:
            raise Cancelled()
        prior = course.knowledge_index or {}
        old_graph = graph_index(prior).get("graph")
        if prior.get("generation") != previous:
            raise ModelError("知识库引擎已更新，请刷新后重试。")
        current = {source.id: source for source in sources_for(db, user_id, course_id).with_for_update()}
        if engine not in {"atlas", "auto"} and source_manifest(current.values()) != manifest:
            raise ModelError("课程资料在索引期间已变化，请重新构建。")
        if signature and signature != embedding_signature():
            raise ModelError("Embedding 配置已变化，请重新构建。")
        if prepared:
            for chunk, vector in zip(missing, prepared.vectors, strict=True):
                saved = db.get(Chunk, chunk.id)
                if not saved or saved.source_id != chunk.source_id or saved.content != chunk.content:
                    raise ModelError("资料片段已变化，请重新构建。")
                saved.embedding = vector
                prepared.bind(current[chunk.source_id])
        IndexCheckpoint(task_id, run_id).clear(db)
        jobs = []
        if automatic_graph:
            if course.knowledge_engine != "auto":
                raise ModelError("课程已改用手动检索引擎，未启用自动图谱。")
            course.knowledge_index = {**prior, "auto_graph": index}
        else:
            course.knowledge_engine = engine
            if engine == "auto" and old_graph:
                index["auto_graph"] = graph_index(prior)
            course.knowledge_index = index
            if engine == "auto":
                for source in current.values():
                    revision = db.query(SourceRevision).filter_by(
                        user_id=user_id, source_id=source.id, version=source.version,
                    ).first()
                    jobs.extend(enqueue_source_indexes(db, course, source, revision))
        task.status, task.progress = "succeeded", 100
        task.message = "课程概念图谱已就绪" if automatic_graph else "课程检索引擎已启用"
        task.result = {"engine": engine, "source_count": len(current)}
        task.error, task.lease_until, task.worker_token = None, None, None
        db.commit()
        dispatch_indexes(jobs)
        return old_graph, graph_index(course.knowledge_index).get("graph")
