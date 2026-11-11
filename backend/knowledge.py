"""Select a retrieval engine for the current course library."""

from importlib.util import find_spec

from backend.indexing import embedding_available, embedding_signature
from backend.models.domain import Course, Source, Task

ENGINES = {"auto": "自动", "atlas": "Atlas", "llamaindex": "LlamaIndex", "pageindex": "PageIndex", "lightrag": "LightRAG"}


def sources_for(db, user_id, course_id):
    return db.query(Source).filter_by(user_id=user_id, course_id=course_id)


def source_manifest(sources):
    return {source.id: [source.version, source.content_hash, source.chunk_count] for source in sources}


def graph_index(index):
    return index.get("auto_graph") or index


def graph_ready(course, index, sources):
    from backend.knowledge_graph import workspace

    return bool(
        embedding_available() and index.get("graph") and index.get("embedding_signature") == embedding_signature()
        and index.get("sources") == source_manifest(sources)
        and workspace(course.user_id, course.id, index["graph"]).is_dir()
    )


def latest_task(db, course):
    return db.query(Task).filter_by(
        user_id=course.user_id, course_id=course.id, kind="knowledge_index",
    ).filter(Task.payload["purpose"].as_string().is_(None)).order_by(
        Task.updated_at.desc(), Task.id.desc(),
    ).first()


def engine_requirement(engine):
    if engine == "pageindex" and find_spec("pageindex") is None:
        return "安装 PageIndex 扩展后可用。"
    if engine == "lightrag":
        if find_spec("lightrag") is None:
            return "安装 LightRAG 扩展后可用。"
        if not embedding_available():
            return "请先配置 Embedding 服务。"
    return None


def state(db, course):
    from backend.serializers import task_json

    task = latest_task(db, course)
    engine = course.knowledge_engine
    index = course.knowledge_index or {}
    sources = sources_for(db, course.user_id, course.id).all()
    stale = engine in {"pageindex", "lightrag"} and index.get("sources") != source_manifest(sources)
    if engine == "lightrag":
        stale = not graph_ready(course, index, sources)
    if engine == "llamaindex":
        signature = embedding_signature()
        stale = embedding_available() and any(
            source.chunk_count and (source.embedding_signature != signature or not source.embedding_dimension)
            for source in sources
        )
    return {
        "engine": engine, "stale": stale, "embedding_configured": embedding_available(),
        "searchable": any(source.chunk_count for source in sources),
        "indexing": db.query(Task.id).filter(
            Task.user_id == course.user_id, Task.course_id == course.id,
            Task.status.in_(["queued", "running"]),
            Task.kind.in_(["knowledge_page", "knowledge_index", "reindex"]),
        ).first() is not None,
        "engines": [{"id": key, "label": label, "unavailable": engine_requirement(key)}
                    for key, label in ENGINES.items()],
        "task": {**task_json(db, task), "engine": task.payload.get("engine")} if task else None,
    }


def note_engine(diagnostics, engine):
    if diagnostics is not None and engine not in diagnostics.setdefault("engines_used", []):
        diagnostics["engines_used"].append(engine)


def note_warning(diagnostics, warning):
    if diagnostics is not None and warning not in diagnostics.setdefault("warnings", []):
        diagnostics["warnings"].append(warning)


async def search(db, user_id, course_id, query, limit, *, source_ids, source_kinds,
                 use_embeddings, diagnostics, native, allow_supplement=False,
                 allow_index_jobs=False, **native_options):
    from backend.llm import ModelError

    course = db.query(Course).filter_by(id=course_id, user_id=user_id).first()
    engine = course.knowledge_engine if course else "atlas"
    if diagnostics is not None:
        diagnostics["engine"] = engine

    async def fallback(*, lexical=False, scope=source_ids, count=limit):
        note_engine(diagnostics, "atlas")
        return await native(
            db, user_id, course_id, query, count, source_ids=scope,
            source_kinds=source_kinds, diagnostics=diagnostics,
            use_embeddings=use_embeddings and not lexical, **native_options,
        )

    if engine == "atlas" or (not use_embeddings and engine not in {"auto", "llamaindex"}):
        return await fallback()
    filters = sources_for(db, user_id, course_id)
    if source_ids is not None:
        filters = filters.filter(Source.id.in_(source_ids))
    if source_kinds is not None:
        filters = filters.filter(Source.kind.in_(source_kinds))
    sources = filters.order_by(Source.id).all()
    if not sources:
        return []
    if engine == "auto":
        from backend.knowledge_auto import search as auto_search

        return await auto_search(
            db, course, sources, query, limit, use_embeddings, diagnostics, fallback,
            allow_supplement=allow_supplement, allow_index_jobs=allow_index_jobs,
            full_scope=source_ids is None and source_kinds is None,
        )
    index = course.knowledge_index or {}
    try:
        if engine == "llamaindex":
            from backend.knowledge_llama import search as hybrid_search

            result = await hybrid_search(
                db, sources, query, limit, use_embeddings,
                lambda value: note_warning(diagnostics, value),
            )
        elif engine == "pageindex":
            from backend.knowledge_pages import search as search_pages

            if engine_requirement(engine):
                raise ModelError("PageIndex 扩展未安装。")
            sections = index.get("sections", {})
            versions = index.get("sources", {})
            current = source_manifest(sources)
            indexed = [source for source in sources if source.id in sections
                       and current[source.id] == versions.get(source.id)]
            if any(current[source.id] != versions.get(source.id) for source in sources):
                note_warning(diagnostics, "knowledge_index_stale")
            indexed_ids = {source.id for source in indexed}
            missing = [source.id for source in sources if source.id not in indexed_ids]
            result = await search_pages(db, indexed, sections, query, limit) if indexed else []
            if indexed:
                note_engine(diagnostics, engine)
            if missing:
                note_warning(diagnostics, "knowledge_source_not_indexed")
            if missing and len(result) < limit:
                result += await fallback(scope=missing, count=limit - len(result))
            return result or await fallback()
        elif engine == "lightrag":
            from backend.knowledge_graph import search as search_graph

            if index.get("sources") != source_manifest(sources_for(db, user_id, course_id)):
                note_warning(diagnostics, "knowledge_index_stale")
                return await fallback()
            result = await search_graph(db, sources, index, query, limit)
            if not result:
                note_engine(diagnostics, engine)
                return await fallback()
        else:
            raise ModelError("检索引擎未就绪。")
    except (ModelError, ImportError):
        note_warning(diagnostics, "knowledge_engine_unavailable")
        return await fallback(lexical=True)
    note_engine(diagnostics, engine)
    return result
