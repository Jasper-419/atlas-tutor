"""Prepare the complete FinanceBench release for Atlas PDF import."""

from concurrent.futures import ProcessPoolExecutor
from functools import partial
from hashlib import sha256
from http.client import HTTPException as HTTPReadError
import io
import json
import logging
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen
import time

REVISION = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
UPSTREAM = f"https://raw.githubusercontent.com/patronus-ai/financebench/{REVISION}"
ANNOTATIONS = "financebench_open_source.jsonl"
ANNOTATIONS_SHA = "a5a2aa673e573e55675fc3c0f9aa38c1cf59d2abc91edb077534f71f10a71877"
MAX_UPLOAD = 12 * 1024 * 1024
MAX_PAGES = 250


def digest(data):
    return sha256(data).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch(cache, remote):
    import certifi

    path = cache / Path(remote).name
    if not path.exists():
        for attempt in range(3):
            try:
                with urlopen(f"{UPSTREAM}/{quote(remote)}", timeout=45,
                             context=ssl.create_default_context(cafile=certifi.where())) as response:
                    data = response.read()
                break
            except (URLError, HTTPReadError, OSError) as error:
                if attempt == 2 or isinstance(error, HTTPError) and error.code == 404:
                    raise
                time.sleep(2 ** attempt)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path.read_bytes()


def annotations(cache):
    data = fetch(cache, f"data/{ANNOTATIONS}")
    if digest(data) != ANNOTATIONS_SHA:
        raise ValueError("FinanceBench annotation checksum mismatch")
    rows = [json.loads(line) for line in data.splitlines() if line]
    if len(rows) != 150 or len({row["financebench_id"] for row in rows}) != len(rows):
        raise ValueError("Expected 150 unique public FinanceBench questions")
    return rows


def gold_pages(row):
    evidence = row["evidence"]
    if not evidence or any(
        item["doc_name"] != row["doc_name"] or type(item["evidence_page_num"]) is not int
        or item["evidence_page_num"] < 0 for item in evidence
    ):
        return set()
    return {item["evidence_page_num"] + 1 for item in evidence}


def page_ranges(texts, max_text):
    """Return consecutive zero-based, half-open ranges that fit Atlas."""
    start, size = 0, 0
    for index, text in enumerate(texts):
        page_size = len(text) + len(f"[第 {index - start + 1} 页]\n") + (2 if index > start else 0)
        if index > start and (index - start >= MAX_PAGES or size + page_size > max_text):
            yield start, index
            start, size = index, 0
            page_size = len(text) + len("[第 1 页]\n")
        if page_size > max_text:
            raise ValueError(f"Page {index + 1} alone exceeds Atlas's text budget")
        size += page_size
    yield start, len(texts)


def write_parts(reader, document, start, stop, output):
    """Copy all pages and available outline entries, splitting on upload bytes if needed."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.append(reader, pages=(start, stop), import_outline=True)
    stream = io.BytesIO()
    writer.write(stream)
    data = stream.getvalue()
    if len(data) > MAX_UPLOAD:
        if stop - start == 1:
            raise ValueError(f"{document} page {stop} alone exceeds Atlas's upload budget")
        mid = (start + stop) // 2
        yield from write_parts(reader, document, start, mid, output)
        yield from write_parts(reader, document, mid, stop, output)
        return
    name = f"{document}__pages-{start + 1:04d}-{stop:04d}.pdf"
    temporary = output / (name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(output / name)
    yield {"file": name, "original_start": start + 1, "original_end": stop,
           "sha256": digest(data), "bytes": len(data)}


def prepare_pdf(cache, output, document):
    from pypdf import PdfReader
    from backend.retrieval import MAX_TEXT

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    data = fetch(cache, f"pdfs/{document}.pdf")
    reader = PdfReader(io.BytesIO(data))
    encrypted = reader.is_encrypted
    if encrypted and not reader.decrypt(""):
        raise ValueError(f"{document} cannot be opened with an empty password")
    texts = [page.extract_text() or "" for page in reader.pages]
    if not texts:
        raise ValueError(f"{document} contains no pages")
    ranges = list(page_ranges(texts, MAX_TEXT))
    if not encrypted and len(ranges) == 1 and len(data) <= MAX_UPLOAD:
        parts = [{"file": f"{document}.pdf", "original_start": 1, "original_end": len(texts),
                  "sha256": digest(data), "bytes": len(data)}]
    else:
        parts = [part for start, stop in ranges for part in write_parts(reader, document, start, stop, output)]
        for part in parts:
            copy = PdfReader(output / part["file"])
            start, stop = part["original_start"] - 1, part["original_end"]
            copied = [page.extract_text() or "" for page in copy.pages]
            if copy.is_encrypted or copied != texts[start:stop]:
                raise ValueError(f"Page text changed during preparation: {part['file']}")
    return {"sha256": digest(data), "bytes": len(data), "pages": len(texts),
            "empty_password": encrypted, "parts": parts}


def freeze(cache, output):
    rows = annotations(cache)
    names = sorted({row["doc_name"] for row in rows})
    output.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        documents = dict(zip(names, pool.map(partial(prepare_pdf, cache, output), names)))
    for row in rows:
        pages = gold_pages(row)
        if not pages or max(pages) > documents[row["doc_name"]]["pages"]:
            raise ValueError(f"Invalid evidence labels: {row['financebench_id']}")
    return {
        "revision": REVISION, "annotation_sha256": ANNOTATIONS_SHA, "documents": documents,
        "cases": dict(sorted((row["financebench_id"], {"document": row["doc_name"]}) for row in rows)),
    }
