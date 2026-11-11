"""LightRAG evidence retrieval with isolated, versioned local workspaces."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import shutil
import tempfile
from uuid import UUID

from sqlalchemy.orm import load_only

from backend.config import get_settings
from backend.indexing import embedding_signature, validate_vectors
from backend.llm import ModelError, complete, embeddings
from backend.models.domain import Chunk

MAX_GRAPH_CHUNKS = 600
INSERT_BATCH = 12


def workspace(user_id, course_id=None, graph=None):
    path = get_settings().data_dir / "knowledge" / str(int(user_id))
    if course_id is None:
        return path
    path /= str(UUID(course_id))
    if graph is None:
        return path
    if not re.fullmatch(r"graph-[a-z0-9_]{8}", graph):
        raise ModelError("图谱索引标识无效。")
    return path / graph


def remove_workspace(user_id, course_id=None, graph=None):
    shutil.rmtree(workspace(user_id, course_id, graph), ignore_errors=True)


@asynccontextmanager
async def open_graph(path, user_id, signature, dimension, task_id=None):
    import numpy as np
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    async def embed(texts):
        if signature != embedding_signature():
            raise ModelError("Embedding 配置已变化，请重建 LightRAG 索引。")
        result = await embeddings(texts)
        validate_vectors(result, len(texts), dimension)
        return np.asarray(result, dtype=np.float32)

    async def model(prompt, system_prompt=None, history_messages=None, response_format=None, **_):
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        messages.extend(history_messages or [])
        messages.append({"role": "user", "content": prompt})
        json_mode = (response_format or {}).get("type") == "json_object"
        result = await complete(messages, user_id,
                                "lightrag_index" if task_id else "lightrag_search", task_id, json_mode)
        return json.dumps(result, ensure_ascii=False) if json_mode else result

    # Explicit backends keep graph storage isolated even when the host runs LightRAG separately.
    graph = LightRAG(
        working_dir=str(path.parent), workspace=path.name,
        kv_storage="JsonKVStorage", vector_storage="NanoVectorDBStorage",
        graph_storage="NetworkXStorage", doc_status_storage="JsonDocStatusStorage",
        embedding_func=EmbeddingFunc(embedding_dim=dimension, func=embed, max_token_size=2048),
        llm_model_func=model, enable_llm_cache=False, enable_llm_cache_for_entity_extract=False,
        max_parallel_insert=2, embedding_func_max_async=3, llm_model_max_async=3,
        entity_extract_max_gleaning=0,
        chunk_token_size=1500, chunk_overlap_token_size=0,
    )
    await graph.initialize_storages()
    try:
        yield graph
    finally:
        try:
            await graph.finalize_storages()
        finally:
            # LightRAG's storage finalizer does not stop the per-instance model queues.
            queues = [graph.embedding_func.func, *graph.role_llm_funcs.values()]
            await asyncio.gather(*(queue.shutdown(graceful=False) for queue in queues))


async def build(path, user_id, chunks, task_id, on_batch):
    unique = {}
    for chunk in chunks:
        if chunk.content.strip():
            unique.setdefault(chunk.content.strip(), chunk.id)
    if not unique:
        raise ModelError("请先添加资料，再建立 LightRAG 图谱。")
    if len(unique) > MAX_GRAPH_CHUNKS:
        raise ModelError(f"LightRAG 每个知识库最多构建 {MAX_GRAPH_CHUNKS} 个资料片段。")
    signature = embedding_signature()
    dimension = validate_vectors(await embeddings(["Atlas embedding dimension check"]), 1)
    items = list(unique.items())
    async with open_graph(path, user_id, signature, dimension, task_id) as graph:
        for offset in range(0, len(items), INSERT_BATCH):
            on_batch(offset, len(items))
            batch = items[offset:offset + INSERT_BATCH]
            ids = ["atlas-" + key for _, key in batch]
            await graph.ainsert([text for text, _ in batch], ids=ids,
                                file_paths=[key + ".txt" for _, key in batch])
            statuses = await graph.doc_status.get_by_ids(ids)
            if len(statuses) != len(ids) or any(not row or row["status"] != "processed" for row in statuses):
                raise ModelError("LightRAG 未能完成全部片段，请检查模型或 Embedding 服务后重建。")
    return {"graph": path.name, "embedding_signature": signature, "embedding_dimension": dimension}


def new_workspace(user_id, course_id):
    root = workspace(user_id, course_id)
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="graph-", dir=root))


async def search(db, sources, index, query, limit):
    from lightrag import QueryParam
    from backend.knowledge_llama import chunk_citation

    signature = index.get("embedding_signature")
    if not signature or signature != embedding_signature():
        raise ModelError("Embedding 配置已变化，请重建 LightRAG 索引。")
    scope = {source.id: source for source in sources}
    user_id, course_id = sources[0].user_id, sources[0].course_id
    path = workspace(user_id, course_id, index["graph"])
    if not path.is_dir():
        raise ModelError("LightRAG 工作区不可用。")
    try:
        async with asyncio.timeout(45):
            async with open_graph(path, user_id, signature, index["embedding_dimension"]) as graph:
                result = await graph.aquery_data(query, QueryParam(
                    mode="mix", top_k=20, chunk_top_k=min(40, limit * 4), enable_rerank=False,
                ))
    except (OSError, TimeoutError, ValueError, RuntimeError):
        raise ModelError("LightRAG 检索暂时不可用。") from None
    if result.get("status") != "success":
        return []
    keys = []
    for row in result.get("data", {}).get("chunks", []):
        name = row.get("file_path")
        if isinstance(name, str) and name.endswith(".txt") and len(name) == 40:
            keys.append(name[:-4])
    if not keys:
        return []
    chunks = {chunk.id: chunk for chunk in db.query(Chunk).filter(
        Chunk.user_id == user_id, Chunk.course_id == course_id, Chunk.source_id.in_(scope),
        Chunk.id.in_(keys),
    ).options(load_only(Chunk.id, Chunk.source_id, Chunk.content, Chunk.chunk_index,
                        Chunk.page_start, Chunk.page_end, Chunk.section))}
    return [chunk_citation(chunks[key], scope[chunks[key].source_id])
            for key in dict.fromkeys(keys) if key in chunks][:limit]
