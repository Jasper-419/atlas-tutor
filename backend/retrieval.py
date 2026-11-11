"""Real parsing, overlapping chunks, BM25-like lexical ranking and optional hybrid RRF."""

import asyncio
import io
import ipaddress
import math
import re
import socket
import ssl
import os
import certifi
import http.client
import zipfile
import base64
from urllib.request import getproxies, proxy_bypass
from urllib.parse import unquote
from collections import Counter
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import cast, func, or_, and_, tuple_
from pgvector.sqlalchemy import Vector
from backend.models import Source, Chunk
from backend.llm import ModelError, embeddings
from backend.indexing import (
    PreparedIndex, build_index, embedding_available, embedding_signature, vector_filter,
)
from backend.library import ensure_revision, chunk_locator

MAX_TEXT = 400000


def parse_document(filename, data):
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext in {"txt", "md"}:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("gb18030")
        elif ext == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise HTTPException(422, "请先移除 PDF 加密。")
            if len(reader.pages) > 250:
                raise HTTPException(413, "PDF 不得超过 250 页。")
            text = "\n\n".join(
                f"[第 {i + 1} 页]\n" + (p.extract_text() or "")
                for i, p in enumerate(reader.pages)
            )
        elif ext == "docx":
            from docx import Document

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if (
                    sum(item.file_size for item in archive.infolist())
                    > 40 * 1024 * 1024
                ):
                    raise HTTPException(413, "DOCX 解压内容过大。")
            document = Document(io.BytesIO(data))
            text = "\n".join(
                [p.text for p in document.paragraphs]
                + [
                    " | ".join(c.text for c in row.cells)
                    for table in document.tables
                    for row in table.rows
                ]
            )
        else:
            raise HTTPException(415, "支持 PDF、TXT、MD 和 DOCX。")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            422, "文档无法解析，请检查文件是否损坏或使用 UTF-8 TXT。"
        ) from None
    if len(text.strip()) < 12:
        raise HTTPException(422, "未提取到足够文字。扫描 PDF 需要先进行 OCR。")
    if len(text) > MAX_TEXT:
        raise HTTPException(413, "提取文本超过 400,000 字符，请拆分资料。")
    return text


def split_text(text, size=1100, overlap=180):
    text = re.sub(r"\n{4,}", "\n\n\n", text.strip())
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


async def prepare_source(text, *, checkpoint=None):
    """Do optional embedding I/O before opening the final write transaction."""
    if not text.strip() or len(text) > MAX_TEXT:
        raise HTTPException(422, "资料不能为空，且不得超过 400,000 字符。")
    return await build_index(split_text(text), embed=embeddings, checkpoint=checkpoint)


async def add_source(db, user_id, course_id, title, text, url=None, kind="text", *, source_id=None, prepared=None):
    if prepared is None:
        prepared = await prepare_source(text)
    elif not isinstance(prepared, PreparedIndex):
        prepared = PreparedIndex(*prepared)
    pieces, vectors = prepared.pieces, prepared.vectors
    source = Source(
        **({"id": source_id} if source_id else {}),
        user_id=user_id,
        course_id=course_id,
        title=title[:255],
        url=url,
        kind=kind,
        chunk_count=len(pieces),
    )
    prepared.bind(source)
    db.add(source)
    db.flush()
    offset = 0
    for i, piece in enumerate(pieces):
        locator, offset = chunk_locator(text, piece, offset)
        db.add(
            Chunk(
                user_id=user_id,
                course_id=course_id,
                source_id=source.id,
                chunk_index=i,
                content=piece,
                embedding=vectors[i] if vectors else None,
                **locator,
            )
        )
    db.flush()
    ensure_revision(db, source, text)
    return source


def tokens(text):
    text = text.lower()
    words = re.findall(r"[a-z0-9_]+(?:[.:-][a-z0-9_]+)+|[a-z0-9_]+", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(run)
        words.extend(run[i : i + 2] for i in range(len(run) - 1))
    return words


def cosine(a, b):
    if len(a) != len(b):
        return 0
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)) or 1
    )


async def search(db, user_id, course_id, query, limit=6, *, source_kinds=None,
                 candidate_limit=1600, neighbor_window=1, source_ids=None, use_embeddings=True,
                 diagnostics=None):
    """Scoped, bounded hybrid retrieval, then inexpensive relevance/diversity reranking.

    Optional diagnostics report unavailable query embeddings only for vector candidates.
    SQL narrows large libraries before BM25. Neighbours retain definitions spanning
    chunk boundaries; generated reports can be excluded when collecting evidence.
    """
    limit = max(1, min(int(limit), 20))
    candidate_limit = max(100, min(int(candidate_limit), 4000))
    neighbor_window = max(0, min(int(neighbor_window), 1))
    query = str(query)[:2000]
    query_tokens = set(tokens(query))
    sources_query = db.query(Source).filter_by(user_id=user_id, course_id=course_id)
    if source_kinds is not None:
        sources_query = sources_query.filter(Source.kind.in_(list(source_kinds)))
    if source_ids is not None:
        sources_query = sources_query.filter(Source.id.in_(list(source_ids)))
    sources = {s.id: s for s in sources_query}
    if not sources or not query_tokens:
        return []
    base = db.query(Chunk).join(Source, Source.id == Chunk.source_id).filter(
        Chunk.user_id == user_id, Chunk.course_id == course_id,
        tuple_(Source.id, Source.version).in_([(source.id, source.version) for source in sources.values()]),
    )
    # Candidate memory and Python tokenization stay bounded even for big courses.
    chunks = base.order_by(Chunk.created_at.desc(), Chunk.chunk_index).limit(candidate_limit).all()
    if len(chunks) == candidate_limit:
        terms = sorted(query_tokens, key=len, reverse=True)[:24]
        matching_titles = [s.id for s in sources.values()
                           if set(tokens(s.title)) & query_tokens]
        conditions = [Chunk.content.ilike("%" + t.replace("%", "").replace("_", "\\_") + "%", escape="\\")
                      for t in terms]
        if matching_titles:
            conditions.append(Chunk.source_id.in_(matching_titles))
        matches = base.filter(or_(*conditions)).order_by(
            Chunk.created_at.desc(), Chunk.chunk_index
        ).limit(candidate_limit).all()
        if matches:
            chunks = matches
    semantic_ids = []

    def warn(reason):
        if diagnostics is not None:
            warnings = diagnostics.setdefault("warnings", [])
            if reason not in warnings:
                warnings.append(reason)

    if use_embeddings:
        signature = embedding_signature()
        signed = [source for source in sources.values() if source.embedding_signature and source.embedding_dimension]
        unsigned_ids = set(sources) - {source.id for source in signed}
        if unsigned_ids and base.filter(Chunk.source_id.in_(unsigned_ids), vector_filter(db)).first():
            warn("embedding_unverified")
        if signed and not embedding_available():
            warn("embedding_unavailable")
        elif signed:
            matching = [source for source in signed if source.embedding_signature == signature]
            if len(matching) < len(signed):
                warn("embedding_model_changed")
            if matching:
                try:
                    result = await embeddings([query])
                except ModelError:
                    result = None
                if not result:
                    warn("embedding_unavailable")
                elif signature != embedding_signature():
                    warn("embedding_model_changed")
                else:
                    query_vector = result[0]
                    dimension = len(query_vector)
                    if any(source.embedding_dimension != dimension for source in matching):
                        warn("embedding_dimension_mismatch")
                    # Check identity in the same query that reads vectors. A concurrent
                    # rebuild may publish after the initial source read.
                    compatible = base.filter(
                        Source.embedding_signature == signature,
                        Source.embedding_dimension == dimension,
                        vector_filter(db),
                    )
                    if db.bind.dialect.name == "postgresql":
                        vector_column = cast(Chunk.embedding, Vector())
                        distance = vector_column.cosine_distance(query_vector)
                        ranked = compatible.with_entities(Chunk.id, distance.label("distance")).filter(
                            func.vector_dims(vector_column) == dimension,
                        ).order_by(distance).limit(40).all()
                        semantic_ids = [(identifier, 1 - float(value)) for identifier, value in ranked]
                        loaded = {chunk.id for chunk in chunks}
                        missing = [identifier for identifier, _ in semantic_ids if identifier not in loaded]
                        if missing:
                            chunks.extend(base.filter(Chunk.id.in_(missing)).all())
                    else:
                        vectors = compatible.with_entities(Chunk.id, Chunk.embedding).filter(
                            Chunk.id.in_([chunk.id for chunk in chunks]),
                        ).all()
                        semantic_ids = sorted(
                            ((identifier, cosine(vector, query_vector)) for identifier, vector in vectors
                             if len(vector) == dimension),
                            key=lambda item: item[1], reverse=True,
                        )[:40]
    if not chunks:
        return []
    term_counts = [Counter(tokens(c.content)) for c in chunks]
    avg_len = sum(sum(c.values()) for c in term_counts) / len(chunks) or 1
    df = {word: sum(word in counts for counts in term_counts) for word in query_tokens}
    lexical = []
    coverage = {}
    for i, counts in enumerate(term_counts):
        score = 0
        length = sum(counts.values())
        for word in query_tokens:
            freq = counts[word]
            idf = math.log(1 + (len(chunks) - df[word] + 0.5) / (df[word] + 0.5))
            score += idf * freq * 2.2 / (freq + 1.2 * (0.25 + 0.75 * length / avg_len))
        title_tokens = set(tokens(sources[chunks[i].source_id].title))
        coverage[i] = len((set(counts) | title_tokens) & query_tokens) / len(query_tokens)
        score += 0.8 * len(title_tokens & query_tokens)
        if score > 0:
            lexical.append((i, score))
    lexical.sort(key=lambda item: item[1], reverse=True)
    scores = {i: 1 / (60 + rank) for rank, (i, _) in enumerate(lexical[:120], 1)}
    if semantic_ids:
        by_id = {c.id: i for i, c in enumerate(chunks)}
        semantic = [(by_id[identifier], value) for identifier, value in semantic_ids if identifier in by_id]
        for rank, (i, value) in enumerate(semantic, 1):
            if value > 0.15:
                scores[i] = scores.get(i, 0) + 1 / (60 + rank)
    # Coverage/phrase bonus reranks the compact fusion pool, not another model call.
    normalized_query = " ".join(query.lower().split())
    for i in scores:
        scores[i] *= 1 + 0.35 * coverage[i]
        if len(normalized_query) > 2 and normalized_query in chunks[i].content.lower():
            scores[i] *= 1.15
    selected = []
    fingerprints = set()
    source_counts = Counter()
    for i in sorted(scores, key=lambda index: scores[index], reverse=True):
        chunk = chunks[i]
        fingerprint = re.sub(r"\s+", "", chunk.content).lower()
        if fingerprint in fingerprints or source_counts[chunk.source_id] >= max(2, (limit + 1) // 2):
            continue
        if any(c.source_id == chunk.source_id and abs(c.chunk_index - chunk.chunk_index) <= neighbor_window for c in selected):
            continue
        selected.append(chunk)
        fingerprints.add(fingerprint)
        source_counts[chunk.source_id] += 1
        if len(selected) >= limit:
            break
    neighbours = []
    if neighbor_window and selected:
        neighbours = base.filter(or_(*[
            and_(Chunk.source_id == c.source_id,
                 Chunk.chunk_index.between(c.chunk_index - neighbor_window, c.chunk_index + neighbor_window))
            for c in selected
        ])).all()
    citations = []
    for chunk in selected:
        source = sources[chunk.source_id]
        context = sorted([c for c in neighbours if c.source_id == chunk.source_id
                          and abs(c.chunk_index - chunk.chunk_index) <= neighbor_window],
                         key=lambda c: c.chunk_index) or [chunk]
        # Remove split_text overlap rather than repeating boundary text three times.
        excerpt = context[0].content
        for adjacent in context[1:]:
            overlap = next((n for n in range(min(220, len(excerpt), len(adjacent.content)), 19, -1)
                            if excerpt.endswith(adjacent.content[:n])), 0)
            excerpt += ("\n" if not overlap else "") + adjacent.content[overlap:]
        citations.append({
            "id": chunk.id, "source_id": source.id, "title": source.title,
            "url": source.url, "excerpt": excerpt[:3600],
            "chunk_index": chunk.chunk_index,
            "chunk_indices": [c.chunk_index for c in context], "kind": source.kind,
            "source_version": source.version,
            "page_start": min((c.page_start for c in context if c.page_start is not None), default=None),
            "page_end": max((c.page_end for c in context if c.page_end is not None), default=None),
            "section": chunk.section,
        })
    return citations


def validate_public_url(url):
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("URL 端口无效。")
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 80, 443}
    ):
        raise ValueError("仅支持不含凭据的公开 HTTP(S) 文档 URL，端口为 80 或 443。")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("禁止访问私有或本机地址。")
    try:
        addresses = list(
            {
                entry[4][0]
                for entry in socket.getaddrinfo(
                    host,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        )
        if not addresses or any(
            not ipaddress.ip_address(ip).is_global for ip in addresses
        ):
            raise ValueError("禁止访问私有、回环、链路本地或保留地址。")
    except socket.gaierror:
        raise ValueError("文档域名无法解析。") from None
    return parsed, addresses[0]


def proxy_for(parsed):
    if proxy_bypass(parsed.hostname):
        return None
    proxies = getproxies()
    raw = proxies.get(parsed.scheme) or proxies.get("all")
    if not raw:
        return None
    proxy = urlsplit(raw)
    if proxy.scheme != "http" or not proxy.hostname:
        raise ValueError(
            "公开文档抓取支持 HTTP CONNECT 代理；请使用 http:// 形式的 HTTPS_PROXY。"
        )
    return proxy


def proxy_headers(proxy):
    if proxy and proxy.username:
        auth = unquote(proxy.username) + ":" + unquote(proxy.password or "")
        return {
            "Proxy-Authorization": "Basic " + base64.b64encode(auth.encode()).decode()
        }
    return {}


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, proxy=None):
        self.origin_host = host
        self.pinned_ip = ip
        self.proxy = proxy
        context = ssl.create_default_context(
            cafile=os.environ.get("SSL_CERT_FILE") or certifi.where(),
            capath=os.environ.get("SSL_CERT_DIR"),
        )
        if proxy:
            super().__init__(
                proxy.hostname, port=proxy.port or 80, timeout=15, context=context
            )
            self.set_tunnel(ip, port, headers=proxy_headers(proxy))
        else:
            super().__init__(host, port=port, timeout=15, context=context)

    def connect(self):
        # Both direct and proxied connections target the validated IP. The original host is only used for SNI/verification.
        target = self.proxy.hostname if self.proxy else self.pinned_ip
        sock = socket.create_connection((target, self.port), timeout=self.timeout)
        self.sock = sock
        if self.proxy:
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.origin_host)


def _fetch(url):
    for _ in range(4):
        parsed, ip = validate_public_url(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        proxy = proxy_for(parsed)
        connection = (
            PinnedHTTPS(parsed.hostname, ip, port, proxy)
            if parsed.scheme == "https"
            else http.client.HTTPConnection(
                proxy.hostname if proxy else ip,
                port=(proxy.port or 80) if proxy else port,
                timeout=15,
            )
        )
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        if proxy and parsed.scheme == "http":
            path = f"http://{ip}:{port}" + path
        try:
            connection.request(
                "GET",
                path,
                headers={
                    **(proxy_headers(proxy) if parsed.scheme == "http" else {}),
                    "Host": parsed.hostname,
                    "User-Agent": "AtlasLearning/1.0 (+public-document-research)",
                    "Accept": "text/html,text/plain,application/pdf",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise ValueError("文档重定向没有目标。")
                url = urljoin(url, target)
                continue
            if response.status != 200:
                raise ValueError(f"文档站点返回 HTTP {response.status}。")
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("公开文档超过 2 MB 研究抓取限制。")
            kind = response.getheader("Content-Type", "").split(";")[0].lower()
        finally:
            connection.close()
        if kind == "application/pdf" or parsed.path.lower().endswith(".pdf"):
            return url, parsed.hostname, parse_document("research.pdf", data)
        if kind not in {
            "text/html",
            "text/plain",
            "text/markdown",
            "application/xhtml+xml",
        }:
            raise ValueError("只研究 HTML、纯文本、Markdown 或 PDF 文档。")
        text = data.decode("utf-8", errors="replace")
        title = parsed.hostname
        if "html" in kind:
            soup = BeautifulSoup(text, "html.parser")
            if soup.title:
                title = soup.title.get_text(" ", strip=True)
            for tag in soup(
                ["script", "style", "nav", "header", "footer", "aside", "noscript"]
            ):
                tag.decompose()
            text = (soup.find("main") or soup.find("article") or soup).get_text(
                "\n", strip=True
            )
        if len(text.strip()) < 100:
            raise ValueError("网页可提取的正文不足。")
        return url, title[:255], text[:MAX_TEXT]
    raise ValueError("文档重定向次数过多。")


async def safe_fetch(url):
    try:
        return await asyncio.to_thread(_fetch, url)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise ValueError("公开文档抓取失败或 TLS 验证失败。") from None
