"""Embedding identity and validation shared by indexing and retrieval."""

from dataclasses import dataclass
import hashlib
import json
import math

from sqlalchemy import func

from backend.config import get_settings
from backend.llm import ModelError, embeddings
from backend.models.domain import Chunk

BATCH_SIZE = 48
RETRIEVAL_WARNINGS = frozenset({
    "embedding_unverified",
    "embedding_model_changed",
    "embedding_dimension_mismatch",
    "embedding_unavailable",
    "hybrid_unavailable",
    "knowledge_engine_unavailable",
    "knowledge_index_stale",
    "knowledge_source_not_indexed",
    "knowledge_index_queue_unavailable",
    "knowledge_pages_not_ready",
    "knowledge_graph_not_ready",
    "knowledge_graph_queued",
    "knowledge_no_specialized_evidence",
})


def embedding_signature():
    settings = get_settings()
    if not settings.embedding_model:
        return None
    # Credentials can rotate without changing the vector space.
    identity = ["openai-embeddings", settings.embedding_base_url.rstrip("/"), settings.embedding_model]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def embedding_available():
    settings = get_settings()
    return bool(settings.embedding_model and settings.embedding_key)


def vector_filter(db):
    # SQLite's JSON column can contain the JSON literal null as well as SQL NULL.
    if db.bind.dialect.name == "sqlite":
        return func.json_type(Chunk.embedding) == "array"
    return Chunk.embedding.is_not(None)


def index_state(db, source):
    signature = embedding_signature()
    configured = embedding_available()
    if source.embedding_signature:
        if not configured:
            state = "embedding_unavailable"
        elif signature != source.embedding_signature:
            state = "embedding_model_changed"
        elif not source.embedding_dimension:
            state = "embedding_unverified"
        else:
            state = "ready"
    else:
        has_vectors = db.query(Chunk.id).filter(
            Chunk.source_id == source.id, Chunk.user_id == source.user_id, vector_filter(db),
        ).first()
        state = "embedding_unverified" if has_vectors else "lexical"
    return {"state": state, "can_rebuild": configured and bool(source.chunk_count)}


@dataclass(frozen=True)
class PreparedIndex:
    pieces: list[str]
    vectors: list[list[float]]
    signature: str | None = None
    reused_batches: int = 0

    @property
    def dimension(self):
        return len(self.vectors[0]) if self.signature and self.vectors else None

    def bind(self, source):
        source.embedding_signature = self.signature if self.vectors else None
        source.embedding_dimension = self.dimension


def validate_vectors(vectors, count, dimension=None):
    if not isinstance(vectors, list) or not vectors or len(vectors) != count:
        raise ModelError("Embedding 未返回全部资料片段的向量。")
    if dimension is None:
        first = vectors[0]
        dimension = len(first) if isinstance(first, list) else 0
    if not 1 <= dimension <= 16000 or any(
        not isinstance(vector, list) or len(vector) != dimension
        or any(type(value) not in (int, float) or abs(value) > 3.4e38 or not math.isfinite(value) for value in vector)
        or not any(vector)
        for vector in vectors
    ):
        raise ModelError("Embedding 向量无效或维度在重建期间变化，请重新发起索引构建。")
    return dimension


async def build_index(pieces, *, embed=None, checkpoint=None, expected_signature=None):
    signature = embedding_signature()
    if expected_signature is not None and signature != expected_signature:
        raise ModelError("Embedding 配置已变化，请重新发起索引重建。")
    if signature is None:
        return PreparedIndex(pieces, [])
    if not embedding_available():
        raise ModelError("请先配置可用的 embedding 服务。")
    if not pieces:
        raise ModelError("资料没有可建立索引的片段。")
    embed = embed or embeddings
    cached = checkpoint.load(pieces, signature) if checkpoint else {}
    vectors, dimension, reused = [], None, 0
    for offset in range(0, len(pieces), BATCH_SIZE):
        texts = pieces[offset:offset + BATCH_SIZE]
        batch = cached.get(offset)
        if batch is not None:
            try:
                dimension = validate_vectors(batch, len(texts), dimension)
                reused += 1
            except ModelError:
                batch = None
        if batch is None:
            if signature != embedding_signature():
                raise ModelError("Embedding 配置已变化，请重新发起索引构建。")
            batch = await embed(texts)
            dimension = validate_vectors(batch, len(texts), dimension)
            if signature != embedding_signature():
                raise ModelError("Embedding 配置已变化，请重新发起索引构建。")
            if checkpoint:
                checkpoint.save(offset, batch, len(pieces))
        vectors.extend(batch)
    if signature != embedding_signature():
        raise ModelError("Embedding 配置已变化，请重新发起索引构建。")
    return PreparedIndex(pieces, vectors, signature, reused)
