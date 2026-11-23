#!/usr/bin/env python3
"""Build v0.1.2: drop low-confidence application_scenario tags from v0.1.1.

Human S-08 label evaluation showed that low-confidence scenario tags were
the main false-positive source (9/30 exact before filtering; 26/30 after
retaining application_scenario tags with confidence >= 0.9). This script
does not touch profiles, achievements, demands, embeddings or TRL; it only
version-bumps files and removes scenario tags below the gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
EVAL = ROOT / "data" / "eval"
MANIFEST = ROOT / "data" / "manifests"
SCENARIO_MIN_CONFIDENCE = 0.9


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-version", default="v0.1.1")
    ap.add_argument("--target-version", default="v0.1.2")
    args = ap.parse_args()
    src, dst = args.source_version, args.target_version

    labels = read_jsonl(PROCESSED / f"achievements_labeled_{src}.jsonl")
    profiles = read_jsonl(PROCESSED / f"capability_profiles_{src}.jsonl")
    achievements = read_jsonl(PROCESSED / f"achievements_clean_{src}.jsonl")
    demands = read_jsonl(PROCESSED / f"demands_{src}.jsonl")
    enterprises = read_jsonl(PROCESSED / f"enterprises_{src}.jsonl")
    embeddings = read_jsonl(PROCESSED / f"embeddings_{src}.jsonl")
    queries = read_jsonl(EVAL / f"retrieval_queries_{src}.jsonl")
    pairs = read_jsonl(EVAL / f"pair_labels_{src}.jsonl")

    dropped = Counter()
    for row in labels:
        row["dataset_version"] = dst
        kept = []
        for tag in row.get("tags") or []:
            if tag.get("dimension") == "application_scenario":
                if float(tag.get("confidence") or 0) < SCENARIO_MIN_CONFIDENCE:
                    dropped["application_scenario"] += 1
                    continue
            kept.append(tag)
        row["tags"] = kept
    for row in achievements:
        row["dataset_version"] = dst
    for row in profiles:
        row["dataset_version"] = dst
    for row in demands:
        row["dataset_version"] = dst
    for row in embeddings:
        row["dataset_version"] = dst
    for row in queries + pairs:
        row["dataset_version"] = dst

    outputs = {
        "achievements_clean": PROCESSED / f"achievements_clean_{dst}.jsonl",
        "demands": PROCESSED / f"demands_{dst}.jsonl",
        "enterprises": PROCESSED / f"enterprises_{dst}.jsonl",
        "labeled": PROCESSED / f"achievements_labeled_{dst}.jsonl",
        "profiles": PROCESSED / f"capability_profiles_{dst}.jsonl",
        "embeddings": PROCESSED / f"embeddings_{dst}.jsonl",
        "queries": EVAL / f"retrieval_queries_{dst}.jsonl",
        "pairs": EVAL / f"pair_labels_{dst}.jsonl",
    }
    write_jsonl(outputs["achievements_clean"], achievements)
    write_jsonl(outputs["demands"], demands)
    write_jsonl(outputs["enterprises"], enterprises)
    write_jsonl(outputs["labeled"], labels)
    write_jsonl(outputs["profiles"], profiles)
    write_jsonl(outputs["embeddings"], embeddings)
    write_jsonl(outputs["queries"], queries)
    write_jsonl(outputs["pairs"], pairs)
    for name in ("retrieval_queries", "pair_labels"):
        (EVAL / f"{name}_{dst}.csv").write_bytes((EVAL / f"{name}_{src}.csv").read_bytes())

    tag_count = sum(len(r.get("tags") or []) for r in labels)
    dims = Counter(t.get("dimension") for r in labels for t in (r.get("tags") or []))
    scenario_records = sum(
        1 for r in labels if any(t.get("dimension") == "application_scenario" for t in (r.get("tags") or []))
    )
    needs = sum(1 for r in labels if r.get("review_status") == "needs_review")
    manifest = {
        "sprint": "2026-11-22",
        "task": "S-08",
        "dataset_version": dst,
        "taxonomy_version": "v0.1",
        "embedding_model_version": "qwen3.7-text-embedding-flash-1024-v1",
        "base_dataset_version": src,
        "base_commit": "2ca420e",
        "run_id": f"{dst}-20261123",
        "source": "v0.1.1 data with low-confidence application_scenario tags removed",
        "correction": {
            "rule": "application_scenario confidence >= 0.9 retained",
            "dropped_application_scenario_tags": dropped["application_scenario"],
            "label_eval_reference": "30 human-confirmed samples: exact scenario 9/30 before, 26/30 after",
        },
        "files": {
            k: {"path": str(v.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(v)}
            for k, v in outputs.items()
        },
        "quality": {
            "achievements": len(achievements),
            "demands": len(demands),
            "enterprises": len(enterprises),
            "achievement_tags": tag_count,
            "tag_dimensions": dict(dims),
            "records_with_application_scenario": scenario_records,
            "needs_review": needs,
            "queries": len(queries),
            "pairs": len(pairs),
            "profile_policy": "150-250 recommended; >250 accepted",
        },
        "evaluation": {"retrieval_queries": len(queries), "pairs": len(pairs), "annotation_status": "frozen"},
    }
    (MANIFEST / f"dataset_{dst}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest["quality"], ensure_ascii=False, indent=2))
    print("dropped", dropped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
