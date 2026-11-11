#!/usr/bin/env python3
"""Run the real Atlas read-only Agent against the full public FinanceBench release."""

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from financebench_dataset import (
    ANNOTATIONS_SHA, MAX_UPLOAD, REVISION, annotations, digest, freeze, gold_pages,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / "evaluations/retrieval/financebench.json"
CACHE = ROOT / "data/financebench/cache"
PREPARED = ROOT / "data/financebench/prepared"
ENGINES = ("atlas", "pageindex", "auto")
METRICS = ("evidence_hit_at_5", "all_evidence_hit_at_5", "first_citation_hit")
OLLAMA_URL = "http://127.0.0.1:11434/v1"
OLLAMA_CHAT = "qwen3:4b-instruct-2507-q4_K_M"
OLLAMA_EMBEDDING = "atlas-qwen3-embedding:0.6b"
INLINE_CITATION = re.compile(r"(?<!\\)\[(\d+)\](?!\()")
NON_PROSE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^\n`]*`|\$\$[\s\S]*?\$\$")


def billing_error(record):
    return "HTTP 402" in (record.get("error") or "")


def interrupted(record):
    return record["status"] in {"queued", "running"} or billing_error(record)


def append_case(path, record):
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def ok(response):
    response.raise_for_status()
    return response.json()


def locator(ref, sources):
    part = sources.get(ref.get("source_id"))
    start = ref.get("page_start")
    end = ref.get("page_end")
    mapped = part is not None and start is not None
    return {
        "citation": ref.get("citation"),
        "expected_source": part is not None,
        "file": part["file"] if part else None,
        "source_version": ref.get("source_version"),
        "local_start": start, "local_end": end,
        "page_start": part["original_start"] + start - 1 if mapped else None,
        "page_end": part["original_start"] + (end or start) - 1 if mapped else None,
    }


def overlaps(ref, page):
    if not ref or not ref["expected_source"] or ref["source_version"] != 1:
        return False
    start = ref["page_start"]
    return bool(
        start is not None and start <= page <= (ref["page_end"] or start)
    )


def grade(record):
    gold = record["gold_pages"]
    found = {page for page in gold if any(overlaps(ref, page) for ref in record["initial_citations"])}
    return {
        "evidence_hit_at_5": bool(found),
        "all_evidence_hit_at_5": len(found) == len(gold),
        "first_citation_hit": record["status"] == "completed"
        and any(overlaps(record["first_citation"], page) for page in gold),
    }


def first_inline_citation(answer):
    match = INLINE_CITATION.search(NON_PROSE.sub(" ", answer))
    return int(match[1]) if match else None


async def task_result(client, task_id):
    from backend.workflows import claim_task, run_task

    if claim_task(task_id) != task_id:
        raise RuntimeError(f"Could not claim task {task_id}")
    await run_task(task_id)
    task = ok(client.get(f"/api/tasks/{task_id}"))
    if task["status"] != "succeeded":
        raise RuntimeError(f"{task['kind']} failed: {task.get('error')}")
    return task["result"]


async def import_pdf(client, course_id, filename, data):
    from backend.config import get_settings
    from backend.database import SessionLocal
    from backend.indexing import embedding_signature
    from backend.models import Source, Task

    upload = ok(client.post(f"/api/courses/{course_id}/imports", files={
        "file": (filename, data, "application/pdf"),
    }))
    source_id = (await task_result(client, upload["id"]))["source_id"]
    with SessionLocal() as db:
        tasks = dict(db.query(Task.kind, Task.id).filter(
            Task.course_id == course_id, Task.kind.in_(("knowledge_page", "reindex")),
            Task.payload["source_id"].as_string() == source_id,
        ).all())
    page_task = tasks.get("knowledge_page")
    indexed = bool(page_task and (await task_result(client, page_task))["page_indexed"])
    if get_settings().embedding_model:
        await task_result(client, tasks["reindex"])
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            if source.embedding_signature != embedding_signature() or not source.embedding_dimension:
                raise RuntimeError(f"Vector index not ready: {filename}")
    return source_id, indexed


async def measure(client, engine, course_id, sources, row):
    from backend.agent.evaluation import redact
    from backend.database import SessionLocal
    from backend.models.tutor import TutorTurn

    started = perf_counter()
    question_id = row["financebench_id"]
    session_id = ok(client.post("/api/tutor/sessions", json={"course_id": course_id}))["id"]
    turn_id = ok(client.post(f"/api/tutor/sessions/{session_id}/turns", json={
        "content": row["question"], "request_id": question_id, "capability": "qa",
    }))["id"]
    async with asyncio.timeout(600):
        while True:
            with SessionLocal() as db:
                status = db.query(TutorTurn.status).filter_by(id=turn_id).scalar()
            if status not in {"queued", "running"}:
                break
            await asyncio.sleep(0.4)
    turn = ok(client.get(f"/api/tutor/turns/{turn_id}"))
    with SessionLocal() as db:
        saved = db.get(TutorTurn, turn_id)
        if saved.input != row["question"]:
            raise RuntimeError(f"Original question was modified: {question_id}")
        messages = (saved.checkpoint or {}).get("messages", [])
    final = ""
    if turn["status"] == "completed" and messages and messages[-1]["role"] == "assistant":
        final = messages[-1].get("content") or ""
    events = turn["events"]
    retrieval = next((event["payload"] for event in events if event["type"] == "retrieval_result"), {})
    if retrieval and retrieval["engine"] != engine:
        raise RuntimeError(f"Expected {engine}, observed {retrieval['engine']}")
    citation_events = [event["payload"]["citations"] for event in events if event["type"] == "citations"]
    first_batch = citation_events[0] if retrieval.get("source_count") else []
    if len(first_batch) != retrieval.get("source_count", 0) or len(first_batch) > 5:
        raise RuntimeError(f"Initial retrieval event and citations disagree for {question_id}")
    number = first_inline_citation(final)
    final_refs = citation_events[-1] if citation_events else []
    first = next((ref for ref in final_refs if ref["citation"] == number), None)
    record = {
        "id": question_id, "document": row["doc_name"], "engine": engine,
        "question_sha256": digest(row["question"].encode()),
        "gold_pages": sorted(gold_pages(row)), "status": turn["status"],
        "error": redact(turn["error"]) if turn.get("error") else None,
        "initial_citations": [locator(ref, sources) for ref in first_batch],
        "first_citation_number": number, "first_citation": locator(first, sources) if first else None,
        "retrieval": retrieval,
        "tool_calls": [event["payload"].get("tool") for event in events if event["type"] == "tool_start"],
        "model_operations": [
            {"step": event["payload"]["name"], "status": event["payload"]["status"]}
            for event in events if event["type"] == "model_operation"
        ],
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return {**record, **grade(record), "final_answer": redact(final)}


def summarize(records):
    result = {}
    for engine in ENGINES:
        cases = [row for row in records if row["engine"] == engine]
        result[engine] = {
            "n": len(cases),
            **{metric: sum(row[metric] for row in cases) for metric in METRICS},
            "statuses": dict(Counter(row["status"] for row in cases)),
            "actual_engines": dict(Counter("+".join(row["retrieval"].get("engines_used", [])) or "none" for row in cases)),
            "routes": dict(Counter(row["retrieval"].get("route_reason") or "none" for row in cases)),
            "warnings": dict(Counter(warning for row in cases for warning in row["retrieval"].get("warnings", []))),
            "without_inline_citation": sum(row["first_citation_number"] is None for row in cases),
        }
    return result


def verify_run(directory, manifest_path, manifest, rows):
    summary = json.loads((directory / "summary.json").read_text())
    records = [json.loads(line) for line in (directory / "cases.jsonl").read_text().splitlines()]
    if summary["manifest_sha256"] != digest(manifest_path.read_bytes()):
        raise ValueError("Run does not match the supplied frozen manifest")
    selected = {row["financebench_id"]: row for row in rows}
    expected = {(engine, identifier) for engine in ENGINES for identifier in selected}
    if len(records) != len(expected) or {(row["engine"], row["id"]) for row in records} != expected:
        raise ValueError("Run contains missing, unexpected or duplicate cases")
    for record in records:
        if interrupted(record):
            raise ValueError(f"Unfinished trial: {record['id']} ({record['engine']})")
        row = selected[record["id"]]
        if (record["document"] != row["doc_name"] or record["gold_pages"] != sorted(gold_pages(row))
                or record["question_sha256"] != digest(row["question"].encode())
                or record["first_citation_number"] != first_inline_citation(record["final_answer"])
                or any(record[key] != value for key, value in grade(record).items())):
            raise ValueError(f"Recorded evidence or score does not match for {record['id']} ({record['engine']})")
        parts = {part["file"]: part for part in manifest["documents"][row["doc_name"]]["parts"]}
        for ref in [*record["initial_citations"], record["first_citation"]]:
            if not ref or not ref["expected_source"] or ref["local_start"] is None:
                continue
            part = parts[ref["file"]]
            start = part["original_start"] + ref["local_start"] - 1
            end = part["original_start"] + (ref["local_end"] or ref["local_start"]) - 1
            if ((start, end) != (ref["page_start"], ref["page_end"])
                    or not part["original_start"] <= start <= end <= part["original_end"]):
                raise ValueError(f"Page mapping does not match for {record['id']} ({record['engine']})")
    if summarize(records) != summary["scores"]:
        raise ValueError("Recorded aggregate scores do not match the per-case evidence")
    print(f"Verified {len(records)} trials against all {len(selected)} original questions")
    print(json.dumps(summary["scores"], ensure_ascii=False, indent=2))


async def evaluate(args, manifest, selected):
    from fastapi.testclient import TestClient
    from backend.config import get_settings
    from backend.connections import resolve_model_config
    from backend.database import SessionLocal
    from backend.main import app
    from backend.models import User
    from backend.tutor.runner import worker_loop

    by_document = {}
    for row in selected:
        by_document.setdefault(row["doc_name"], []).append(row)
    if not by_document:
        raise ValueError("No questions selected")
    if get_settings().max_upload_bytes != MAX_UPLOAD:
        raise ValueError("Evaluation requires the default 12 MiB upload limit")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    indexes = {}
    with TestClient(app) as client:
        email = "financebench@evaluation.invalid"
        ok(client.post("/api/auth/register", json={
            "email": email, "password": "FinanceBenchEvalOnly!2026", "full_name": "Atlas learner",
        }))
        with SessionLocal() as db:
            user_id = db.query(User.id).filter_by(email=email).scalar()
        model = resolve_model_config(user_id)
        if not model.configured:
            raise ValueError("A live model is required. Configure a key in .env first.")
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "atlas_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "financebench_revision": manifest["revision"], "manifest_sha256": digest(args.manifest.read_bytes()),
            "questions": len(selected), "documents": len(by_document),
            "model": model.model, "protocol": model.protocol,
            "embedding": get_settings().embedding_model or False, "capability": "qa",
            "jobs": args.jobs, "python": sys.version.split()[0],
            "hash_seed": os.environ.get("PYTHONHASHSEED", "random"),
            "runner_sha256": {
                name: digest((ROOT / "scripts" / name).read_bytes())
                for name in ("evaluate_financebench.py", "financebench_dataset.py")
            },
            "versions": {name: version(name) for name in ("pageindex", "pypdf", "llama-index-retrievers-bm25", "bm25s")},
        }
        if getattr(args, "local_ollama", False):
            metadata["ollama"] = args.ollama_metadata
        index_file = args.output / "page-indexes.json"
        run_file = args.output / "run.json"
        case_file = args.output / "cases.jsonl"
        if args.resume:
            previous = json.loads(run_file.read_text())
            if any(previous.get(key) != value for key, value in metadata.items() if key != "created_at"):
                raise ValueError("Resume requires the original model, manifest, runner and settings")
            metadata = previous
            if case_file.exists():
                records = [json.loads(line) for line in case_file.read_text().splitlines()]
                retained = [record for record in records if not interrupted(record)]
                if len(retained) != len(records):
                    for record in records:
                        if interrupted(record):
                            append_case(args.output / "interruptions.jsonl", record)
                    temporary = case_file.with_suffix(".tmp")
                    temporary.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in retained))
                    temporary.replace(case_file)
                    records = retained
            if index_file.exists():
                indexes = json.loads(index_file.read_text())
        elif case_file.exists():
            raise FileExistsError(case_file)
        else:
            write_json(run_file, metadata)
        done = {(record["engine"], record["id"]) for record in records}
        expected = {(engine, row["financebench_id"]) for engine in ENGINES for row in selected}
        if len(done) != len(records) or not done <= expected:
            raise ValueError("Partial run contains unexpected or duplicate cases")
        import_slots = asyncio.Semaphore(args.jobs)
        turn_slots = asyncio.Semaphore(args.jobs)
        out_of_balance = asyncio.Event()

        async def run_case(engine, course_id, sources, row):
            async with turn_slots:
                if out_of_balance.is_set():
                    return
                record = await measure(client, engine, course_id, sources, row)
            records.append(record)
            append_case(case_file, record)
            if billing_error(record):
                out_of_balance.set()
            if len(records) % 10 == 0:
                print(f"{len(records)}/{3 * len(selected)} {engine} {record['id']} {record['status']}", flush=True)

        async def document_run(document, rows):
            pending = {engine: [row for row in rows if (engine, row["financebench_id"]) not in done]
                       for engine in ENGINES}
            if not any(pending.values()):
                return
            async with import_slots:
                if out_of_balance.is_set():
                    return
                course_id = ok(client.post("/api/courses", json={"goal": "Document QA"}))["id"]
                sources = {}
                indexes[document] = {}
                for part in manifest["documents"][document]["parts"]:
                    filename = part["file"]
                    directory = args.cache if filename == f"{document}.pdf" else args.prepared
                    data = (directory / filename).read_bytes()
                    if digest(data) != part["sha256"]:
                        raise ValueError(f"PDF checksum mismatch: {filename}")
                    source_id, indexed = await import_pdf(client, course_id, filename, data)
                    if source_id in sources:
                        raise ValueError(f"Atlas deduplicated distinct page ranges: {filename}")
                    sources[source_id] = part
                    indexes[document][filename] = indexed
                write_json(index_file, indexes)
                for engine, questions in pending.items():
                    if not questions:
                        continue
                    task = ok(client.post(f"/api/courses/{course_id}/knowledge", json={"engine": engine}))
                    result = await task_result(client, task["id"])
                    if result["engine"] != engine:
                        raise RuntimeError(f"Could not select {engine} for {document}")
                    async with asyncio.TaskGroup() as cases:
                        for row in questions:
                            cases.create_task(run_case(engine, course_id, sources, row))

        stop = asyncio.Event()
        workers = [asyncio.create_task(worker_loop(stop)) for _ in range((args.jobs + 1) // 2)]
        try:
            async with asyncio.TaskGroup() as tasks:
                for document, rows in by_document.items():
                    tasks.create_task(document_run(document, rows))
        finally:
            stop.set()
            await asyncio.gather(*workers)

    if out_of_balance.is_set():
        raise RuntimeError("Provider returned HTTP 402; restore balance and use --resume")
    if len(records) != len(selected) * len(ENGINES):
        raise RuntimeError("Incomplete evaluation")
    report = {
        **metadata, "completed_at": datetime.now(timezone.utc).isoformat(),
        "pdf_parts": sum(map(len, indexes.values())),
        "page_indexes_ready": sum(sum(parts.values()) for parts in indexes.values()),
        "scores": summarize(records),
    }
    write_json(args.output / "summary.json", report)
    print(json.dumps(report["scores"], ensure_ascii=False, indent=2))


def evaluation_environment(scratch, mode, local_ollama=False):
    from backend.agent.evaluation import isolated_env

    env = isolated_env(scratch, mode)
    env["MAX_UPLOAD_MB"] = "12"
    if local_ollama:
        env.update(OPENAI_BASE_URL=OLLAMA_URL, OPENAI_API_KEY="ollama", OPENAI_MODEL=OLLAMA_CHAT,
                   DEEPSEEK_API_KEY="", EMBEDDING_BASE_URL=OLLAMA_URL,
                   EMBEDDING_API_KEY="ollama", EMBEDDING_MODEL=OLLAMA_EMBEDDING)
    for key in tuple(os.environ):
        if key.startswith("ATLAS_AGENT_"):
            del os.environ[key]
            env.pop(key, None)
    os.environ.update(env)


def run_worker(args, manifest, rows):
    with TemporaryDirectory(prefix="atlas-agent-eval-financebench-") as scratch:
        evaluation_environment(scratch, "live", getattr(args, "local_ollama", False))
        asyncio.run(evaluate(args, manifest, rows))


def ollama_metadata():
    import httpx

    with httpx.Client(base_url=OLLAMA_URL.removesuffix("/v1"), timeout=15, trust_env=False) as client:
        installed = {item["name"]: item["digest"] for item in ok(client.get("/api/tags"))["models"]}
        required = (OLLAMA_CHAT, OLLAMA_EMBEDDING)
        missing = [name for name in required if name not in installed]
        if missing:
            raise ValueError("Prepare the missing local models as described in FINANCEBENCH.md: " + ", ".join(missing))
        return {"version": ok(client.get("/api/version"))["version"],
                "model_digests": {name: installed[name] for name in required}}


def run_parallel(args, manifest, rows):
    by_document = {}
    for row in rows:
        by_document.setdefault(row["doc_name"], []).append(row)
    documents = sorted(by_document, key=lambda name: (-len(by_document[name]), name))
    folders = [args.output / f"worker-{number + 1}" for number in range(args.workers)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for number, directory in enumerate(folders):
            shard = [row for name in documents[number::args.workers] for row in by_document[name]]
            child = argparse.Namespace(**vars(args))
            child.output = directory
            child.resume = args.resume and (directory / "run.json").exists()
            futures.append(pool.submit(run_worker, child, manifest, shard))
        for future in futures:
            future.result()
    records, indexes = [], {}
    for directory in folders:
        records.extend(json.loads(line) for line in (directory / "cases.jsonl").read_text().splitlines())
        indexes.update(json.loads((directory / "page-indexes.json").read_text()))
    metadata = json.loads((folders[0] / "run.json").read_text())
    metadata.update(questions=len(rows), documents=len(by_document), workers=args.workers)
    write_json(args.output / "run.json", metadata)
    write_json(args.output / "page-indexes.json", indexes)
    with (args.output / "cases.jsonl").open("w", encoding="utf-8") as output:
        for record in sorted(records, key=lambda item: (item["engine"], item["id"])):
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        **metadata, "completed_at": datetime.now(timezone.utc).isoformat(),
        "pdf_parts": sum(map(len, indexes.values())),
        "page_indexes_ready": sum(sum(parts.values()) for parts in indexes.values()),
        "scores": summarize(records),
    }
    write_json(args.output / "summary.json", summary)
    verify_run(args.output, args.manifest, manifest, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--prepared", type=Path, default=PREPARED)
    parser.add_argument("--output", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true", help="Prepare PDFs and map all original pages")
    modes.add_argument("--verify-run", type=Path, help="Regrade an existing run without calling a model")
    parser.add_argument("--jobs", type=int, choices=range(1, 17), metavar="1-16", default=8)
    parser.add_argument("--workers", type=int, choices=range(1, 5), metavar="1-4", default=1)
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted run in the same output directory")
    parser.add_argument("--local-ollama", action="store_true", help="Use local Qwen chat and embeddings")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    if not args.prepare:
        manifest = json.loads(args.manifest.read_text())
        if manifest["revision"] != REVISION or manifest["annotation_sha256"] != ANNOTATIONS_SHA:
            raise ValueError("Unexpected FinanceBench release")
        rows = annotations(args.cache)
        if (set(manifest["cases"]) != {row["financebench_id"] for row in rows}
                or any(manifest["cases"][row["financebench_id"]]["document"] != row["doc_name"] for row in rows)):
            raise ValueError("Manifest and annotation case identities differ")
        if args.verify_run:
            verify_run(args.verify_run, args.manifest, manifest, rows)
            return
        if args.output is None:
            parser.error("--output is required for live evaluation")
        if args.local_ollama:
            args.ollama_metadata = ollama_metadata()
    if args.prepare:
        with TemporaryDirectory(prefix="atlas-agent-eval-financebench-") as scratch:
            evaluation_environment(scratch, "fixture")
            manifest = freeze(args.cache, args.prepared)
            write_json(args.manifest, manifest)
            print(f"Prepared {len(manifest['documents'])} PDFs for all {len(manifest['cases'])} questions")
    elif args.workers == 1:
        run_worker(args, manifest, rows)
    else:
        run_parallel(args, manifest, rows)


if __name__ == "__main__":
    main()
