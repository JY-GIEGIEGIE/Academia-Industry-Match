#!/usr/bin/env python3
"""Validate the thin-slice data against data_contract_v0.1.md.

Checks:
- 100 achievements, unique IDs, required fields
- subfield counts (15 main + 5 auxiliary)
- abstract length and language distribution
- 20 demands / 10 enterprises / 20 eval queries / 50 pair labels
- simulated flags on demand/enterprise seeds

Usage:
    python scripts/data/validate_thin_slice.py --version v0.1-thin
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from config import EVAL_DIR, PROCESSED_DIR, SAMPLE_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ACHIEVEMENT_FIELDS = [
    "achievement_id",
    "source",
    "source_id",
    "title_original",
    "abstract_original",
    "language",
    "publication_year",
    "type",
    "source_url",
    "retrieved_at",
    "content_hash",
]


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(0, sum(1 for _ in csv.DictReader(handle)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the thin slice.")
    parser.add_argument("--version", default="v0.1-thin")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    achievements_path = PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    if not achievements_path.exists():
        print(f"Missing {achievements_path}", file=sys.stderr)
        return 2

    achievements = load_jsonl(achievements_path)
    if len(achievements) != 100:
        errors.append(f"achievement count is {len(achievements)}, expected 100")

    ids = [record["achievement_id"] for record in achievements]
    if len(ids) != len(set(ids)):
        errors.append("duplicate achievement_id values")

    for record in achievements:
        missing = [field for field in REQUIRED_ACHIEVEMENT_FIELDS if not record.get(field)]
        if missing:
            errors.append(f"{record.get('achievement_id', '?')} missing {missing}")

    tag_counts = Counter(record["query_tag"] for record in achievements)
    expected = {"cathode": 15, "anode": 15, "electrolyte": 15, "separator": 15,
                "cell_system": 15, "recycling": 15, "flow": 5, "supercap": 5}
    for tag, expected_count in expected.items():
        actual = tag_counts.get(tag, 0)
        if actual < expected_count:
            warnings.append(f"{tag}: {actual} records, expected {expected_count}")

    languages = Counter(record["language"] for record in achievements)
    if languages.get("zh", 0) == 0 and languages.get("mixed", 0) == 0:
        warnings.append("no Chinese-language achievements; Chinese display will rely on generated profiles")

    short_abstracts = [
        record["achievement_id"]
        for record in achievements
        if len(record["abstract_original"]) < 200
    ]
    if short_abstracts:
        errors.append(f"{len(short_abstracts)} abstracts shorter than 200 chars")

    demands_path = SAMPLE_DIR / "demands_seed_v0.1.jsonl"
    enterprises_path = SAMPLE_DIR / "enterprises_seed_v0.1.jsonl"
    demands = load_jsonl(demands_path) if demands_path.exists() else []
    enterprises = load_jsonl(enterprises_path) if enterprises_path.exists() else []
    if len(demands) != 20:
        errors.append(f"demand count is {len(demands)}, expected 20")
    if len(enterprises) != 10:
        errors.append(f"enterprise count is {len(enterprises)}, expected 10")
    if any(not item.get("is_simulated") for item in demands):
        errors.append("some demands are not marked is_simulated=true")
    if any(not item.get("is_simulated") for item in enterprises):
        errors.append("some enterprises are not marked is_simulated=true")

    retrieval_csv = EVAL_DIR / f"retrieval_queries_{args.version}.csv"
    pair_csv = EVAL_DIR / f"pair_labels_{args.version}.csv"
    retrieval_count = count_csv_rows(retrieval_csv) if retrieval_csv.exists() else 0
    pair_count = count_csv_rows(pair_csv) if pair_csv.exists() else 0
    if retrieval_count != 20:
        errors.append(f"retrieval query count is {retrieval_count}, expected 20")
    if pair_count != 50:
        errors.append(f"pair label count is {pair_count}, expected 50")

    print("Thin-slice validation")
    print(f"  achievements: {len(achievements)} | unique IDs: {len(set(ids))}")
    print(f"  by tag: {dict(tag_counts)}")
    print(f"  languages: {dict(languages)}")
    print(f"  demands: {len(demands)} | enterprises: {len(enterprises)}")
    print(f"  retrieval queries: {retrieval_count} | pair labels: {pair_count}")
    if warnings:
        print("\nWarnings")
        for warning in warnings:
            print(f"  - {warning}")
    if errors:
        print("\nErrors")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nOK: thin slice matches the v0.1 contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
