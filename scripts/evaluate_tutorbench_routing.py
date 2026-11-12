#!/usr/bin/env python3
"""Compare two Atlas revisions on a fixed, unseen TutorBench text cohort."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import evaluate_tutorbench as bench
import tutorbench_scoring as scoring

OUTPUT = bench.DATA / "routing-heldout"
LOCK = bench.ROOT / "evaluations/tutorbench/routing-heldout.json"
ARMS = ("before", "after")
SUBJECTS = ("Biology", "Calculus", "Chemistry", "Physics", "Statistics")
PER_STRATUM = 2
SALT = "atlas-tutor-routing-heldout-v1"


def prepare(cache, output):
    import pyarrow.parquet as pq

    expected = bench.read_json(bench.MANIFEST)
    previous_ids = {item for ids in expected["ids"].values() for item in ids}
    rows = []
    for index, filename in enumerate(bench.FILES):
        path = cache / f"train-{index:05d}.parquet"
        if bench.sha_file(path) != expected["source_sha256"][filename]:
            raise ValueError(f"TutorBench source checksum mismatch: {filename}")
        rows.extend(pq.read_table(path, columns=list(bench.FIELDS)).to_pylist())
    if len(rows) != expected["upstream_rows"] or len({row["TASK_ID"] for row in rows}) != len(rows):
        raise ValueError("Unexpected TutorBench source rows")

    selected = []
    for subject in SUBJECTS:
        for batch in bench.TASKS:
            candidates = sorted(
                (row for row in rows if row["SUBJECT"] == subject and row["BATCH"] == batch),
                key=lambda row: bench.sha_bytes(f"{SALT}/{row['TASK_ID']}".encode()),
            )
            if len(candidates) < PER_STRATUM:
                raise ValueError(f"Not enough {subject} {batch} cases")
            selected.extend(candidates[:PER_STRATUM])
    ids = [row["TASK_ID"] for row in selected]
    if previous_ids.intersection(ids):
        raise ValueError("The held-out cohort overlaps the 84 diagnostic questions")
    cohort = output / "cohort.json"
    bench.write_json(cohort, {"dataset": bench.DATASET, "revision": bench.REVISION, "cases": selected})
    manifest = {
        "dataset": bench.DATASET,
        "revision": bench.REVISION,
        "source_sha256": expected["source_sha256"],
        "selection": {"subjects": list(SUBJECTS), "batches": list(bench.TASKS), "per_stratum": PER_STRATUM,
                      "order": f"ascending SHA-256 of {SALT}/TASK_ID within each stratum"},
        "excluded_diagnostic_ids": len(previous_ids),
        "cohort_sha256": bench.sha_file(cohort),
        "ids": ids,
    }
    if LOCK.exists():
        if bench.read_json(LOCK) != manifest:
            raise ValueError("Selection differs from the locked held-out manifest")
    else:
        bench.write_json(LOCK, manifest)
    print(f"Prepared {len(ids)} locked held-out questions ({manifest['cohort_sha256']})", flush=True)


def load_rows(output):
    path = output / "cohort.json"
    manifest = bench.read_json(LOCK)
    if bench.sha_file(path) != manifest["cohort_sha256"]:
        raise ValueError("Held-out cohort checksum mismatch")
    data = bench.read_json(path)
    rows = data["cases"]
    if data["revision"] != bench.REVISION or [row["TASK_ID"] for row in rows] != manifest["ids"]:
        raise ValueError("Unexpected held-out question IDs or dataset revision")
    if Counter((row["SUBJECT"], row["BATCH"]) for row in rows) != {
        (subject, batch): PER_STRATUM for subject in SUBJECTS for batch in bench.TASKS
    }:
        raise ValueError("Unexpected held-out subject and task strata")
    return rows


def generate(rows, output, arm, atlas_root, jobs):
    atlas_root = atlas_root.resolve()
    if not (atlas_root / "backend/tutor/runner.py").is_file():
        raise ValueError("--atlas-root must point to an Atlas checkout")
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "backend"], cwd=atlas_root, check=True)
    if subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "backend"], cwd=atlas_root):
        raise ValueError("Commit the Atlas backend before recording benchmark results")
    metadata = bench.generation_metadata(output / "cohort.json", jobs)
    metadata.update(
        atlas_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=atlas_root, text=True).strip(),
        run_order="same seeded question order in separate revision runs",
        orchestration_sha256=bench.sha_file(Path(__file__)),
    )
    path = output / f"generation-{arm}.json"
    if path.exists() and bench.read_json(path) != metadata:
        raise ValueError("Generation conditions changed for this arm")
    other_path = output / f"generation-{ARMS[1 - ARMS.index(arm)]}.json"
    if other_path.exists():
        other = bench.read_json(other_path)
        if other == metadata or any(other[key] != value for key, value in metadata.items() if key != "atlas_commit"):
            raise ValueError("Generation must compare distinct Atlas revisions with identical model conditions")
    bench.write_json(path, metadata)

    # Generate each revision in its own process and isolated database. The
    # original harness admits only one trial arm during that run.
    sys.path.insert(0, str(atlas_root))
    import backend

    if not Path(backend.__file__).resolve().is_relative_to(atlas_root):
        raise RuntimeError("Benchmark imported the wrong Atlas revision")
    original_usage = bench.usage_summary

    def usage_summary(events):
        usage = original_usage(events)
        routes = [event["payload"]["route"] for event in events if event["type"] == "answer_route"]
        if routes:
            usage["answer_route"] = routes[0]
        return usage

    with (TemporaryDirectory(prefix=f"atlas-tutor-{arm}-") as scratch,
          patch.object(bench, "ARMS", (arm,)), patch.object(bench, "usage_summary", usage_summary)):
        bench.isolated_settings(Path(scratch))
        arm_output = output / arm
        arm_output.mkdir(exist_ok=True)
        asyncio.run(bench.generate(rows, arm_output, jobs))


def judge(rows, output, jobs):
    all_responses = [
        response for arm in ARMS for response in bench.read_lines(output / arm / "responses.jsonl")
    ]
    if len(all_responses) != len(rows) * len(ARMS):
        raise ValueError("Both Atlas revisions must complete generation before judging")
    path = output / "responses.jsonl"
    if path.exists() and bench.read_lines(path) != all_responses:
        raise ValueError("Existing merged responses differ from the revision outputs")
    if not path.exists():
        for response in all_responses:
            bench.append(path, response)
    bench.write_json(output / "generation.json", {
        arm: bench.read_json(output / f"generation-{arm}.json") for arm in ARMS
    })
    judge_system = bench.JUDGE_SYSTEM.replace("Computer Science tutor", "STEM tutor")
    with patch.object(scoring, "ARMS", ARMS), patch.object(scoring, "JUDGE_SYSTEM", judge_system):
        asyncio.run(scoring.judge(rows, output, jobs))
        asyncio.run(scoring.judge_hint_leakage(rows, output, jobs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "generate", "judge", "report"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--cache", type=Path, default=bench.DATA / "upstream")
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--atlas-root", type=Path)
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.cache, args.output)
        return
    rows = load_rows(args.output)
    if args.phase == "generate":
        if args.arm is None or args.atlas_root is None:
            parser.error("generate requires --arm and --atlas-root")
        generate(rows, args.output, args.arm, args.atlas_root, args.jobs)
    elif args.phase == "judge":
        judge(rows, args.output, args.jobs)
    else:
        with patch.object(scoring, "ARMS", ARMS):
            scoring.report(rows, args.output, labels=("Atlas before", "Atlas after"),
                           title="TutorBench held-out STEM paired evaluation")


if __name__ == "__main__":
    main()
