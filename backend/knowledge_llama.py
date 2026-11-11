"""LlamaIndex BM25 and vector search over Atlas-owned chunks."""

import asyncio
from collections import defaultdict
from functools import lru_cache

from sqlalchemy.orm import load_only

from backend.indexing import embedding_available, embedding_signature, validate_vectors
from backend.llm import ModelError, embeddings
from backend.models.domain import Chunk, Source

MAX_CHUNKS = 3000


@lru_cache(maxsize=3)
def bm25_index(records):
    from llama_index.core.schema import TextNode
    from llama_index.retrievers.bm25 import BM25Retriever

    nodes = [TextNode(id_=identifier, text=text) for identifier, text in records if text]
    if not nodes:
        return None
    return BM25Retriever.from_defaults(
        nodes=nodes, language=[], skip_stemming=True, token_pattern=r"[^\s]+",
        similarity_top_k=min(40, len(nodes)),
    )


def token_text(text):
    from backend.retrieval import tokens

    return " ".join(tokens(text))


def ranked(records, query, vectors, query_vector, limit):
    from llama_index.core.schema import TextNode
    from llama_index.core.vector_stores import SimpleVectorStore, VectorStoreQuery

    index = bm25_index(records)
    lexical = []
    if index and query:
        lexical = [node.node.node_id for node in index.retrieve(query) if node.score > 0]
    semantic = []
    if vectors:
        store = SimpleVectorStore()
        store.add([TextNode(id_=key, embedding=vector) for key, vector in vectors])
        matches = store.query(VectorStoreQuery(query_embedding=query_vector, similarity_top_k=40))
        semantic = [key for key, score in zip(matches.ids, matches.similarities) if score > 0.15]
    scores = defaultdict(float)
    for results in (lexical, semantic):
        for rank, key in enumerate(results, 1):
            scores[key] += 1 / (60 + rank)
    return sorted(scores, key=scores.get, reverse=True)[:limit]


def library_chunks(db, sources):
    return (
        db.query(Chunk, Source.version, Source.embedding_signature, Source.embedding_dimension)
        .join(Source, Source.id == Chunk.source_id)
        .filter(
            Chunk.user_id == sources[0].user_id, Chunk.course_id == sources[0].course_id,
            Source.user_id == sources[0].user_id, Source.course_id == sources[0].course_id,
            Source.id.in_([source.id for source in sources]),
        )
        .order_by(Chunk.source_id, Chunk.chunk_index)
    )


async def search(db, sources, query, limit, use_embeddings, warn):
    base = library_chunks(db, sources)
    rows = base.options(load_only(Chunk.id, Chunk.source_id, Chunk.chunk_index, Chunk.content,
                                 Chunk.page_start, Chunk.page_end, Chunk.section)).limit(MAX_CHUNKS + 1).all()
    versions = {source.id: source for source in sources}
    if len(rows) > MAX_CHUNKS:
        raise ModelError("课程资料超过 LlamaIndex 本地索引容量。")
    current = {
        chunk.id: chunk for chunk, version, _, _ in rows
        if versions[chunk.source_id].version == version
    }
    if not current:
        return []
    signature = embedding_signature()
    vectors, query_vector = [], None
    if use_embeddings:
        if not embedding_available():
            warn("embedding_unavailable")
        elif any(signed == signature and dimension for _, _, signed, dimension in rows):
            if any(signed != signature or not dimension for _, _, signed, dimension in rows):
                warn("embedding_model_changed")
            try:
                result = await embeddings([query])
                dimension = validate_vectors(result, 1)
                query_vector = result[0]
            except ModelError:
                warn("embedding_unavailable")
            if signature != embedding_signature():
                warn("embedding_model_changed")
            elif query_vector:
                matches = base.with_entities(Chunk.id, Chunk.embedding).filter(
                    Source.embedding_signature == signature, Source.embedding_dimension == dimension,
                    Chunk.id.in_(list(current)),
                )
                vectors = [(key, vector) for key, vector in matches if vector and len(vector) == dimension]
                if not vectors or any(signed == signature and size != dimension
                                      for _, _, signed, size in rows):
                    warn("embedding_dimension_mismatch")
        else:
            warn("embedding_model_changed")
    records = tuple(
        (key, token_text(versions[chunk.source_id].title + " " + chunk.content))
        for key, chunk in current.items()
    )
    keys = await asyncio.to_thread(ranked, records, token_text(query), vectors, query_vector, limit)
    return [chunk_citation(current[key], versions[current[key].source_id]) for key in keys]


def chunk_citation(chunk, source):
    return {
        "id": chunk.id, "source_id": source.id, "title": source.title, "url": source.url,
        "excerpt": chunk.content, "chunk_index": chunk.chunk_index, "chunk_indices": [chunk.chunk_index],
        "kind": source.kind, "source_version": source.version, "page_start": chunk.page_start,
        "page_end": chunk.page_end, "section": chunk.section,
    }
