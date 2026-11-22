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

from build_thin_slice import deduplicate, source_id_from_openalex
from config import (
    APPLICATION_SCENARIOS,
    COOPERATION_MODES,
    EVAL_DIR,
    FULL_VERSION,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLE_DIR,
    TECH_FIELDS,
    subfield_specs,
)

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
    parser = argparse.ArgumentParser(description="Validate the thin slice or the v0.1 dataset.")
    parser.add_argument("--version", default="v0.1-thin")
    return parser.parse_args()


def validate_full_dataset() -> int:
    names = ("achievements_clean", "demands", "enterprises")
    paths = [PROCESSED_DIR / f"{name}_{FULL_VERSION}.jsonl" for name in names]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        print("Missing files: " + ", ".join(missing), file=sys.stderr)
        return 2

    achievements, demands, enterprises = (load_jsonl(path) for path in paths)
    errors: list[str] = []
    if not 300 <= len(achievements) <= 400:
        errors.append(f"achievement count {len(achievements)} is outside 300–400")
    if len(demands) != 100 or len(enterprises) != 25:
        errors.append(f"expected 100 demands and 25 enterprises, got {len(demands)}/{len(enterprises)}")

    counts = Counter(row.get("query_tag") for row in achievements)
    specs = subfield_specs(FULL_VERSION)
    if set(counts) != set(specs) or any(counts[tag] < spec["target"] for tag, spec in specs.items()):
        errors.append(f"subfield quotas not met: {dict(counts)}")

    core = ("title_original", "abstract_original", "language", "publication_year",
            "source_url", "retrieved_at", "content_hash")
    if any(not all(row.get(field) for field in core) for row in achievements):
        errors.append("one or more achievements are missing a mandatory source/text field")
    required = REQUIRED_ACHIEVEMENT_FIELDS + ["clean_status", "review_status", "dataset_version"]
    complete = sum(
        all(row.get(field) for field in required) and row.get("is_simulated") is False
        for row in achievements
    )
    completeness = complete / len(achievements) if achievements else 0.0
    if completeness < 0.95:
        errors.append("achievement required-field completeness below 95%")
    if any(row.get("is_simulated") is not False or row.get("dataset_version") != FULL_VERSION
           for row in achievements):
        errors.append("invalid achievement version or simulation flag")

    if all(row.get("source_id") and row.get("title_original") for row in achievements):
        _, duplicate_count = deduplicate(achievements)
    else:
        duplicate_count = len(achievements)
    duplicate_rate = duplicate_count / len(achievements) if achievements else 0.0
    achievement_ids = {row.get("achievement_id") for row in achievements}
    if duplicate_rate >= 0.02 or len(achievement_ids) != len(achievements):
        errors.append("duplicate rate reached 2% or achievement IDs repeat")

    raw_ids: dict[Path, set[str]] = {}
    traced = 0
    for row in achievements:
        raw_path = (PROJECT_ROOT / row.get("raw_payload_path", "")).resolve()
        if not raw_path.is_relative_to(RAW_DIR.resolve()) or not raw_path.is_file():
            continue
        if raw_path not in raw_ids:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_ids[raw_path] = {source_id_from_openalex(work) for work in raw.get("results", [])}
        if (row.get("source") == "openalex" and row.get("source_url", "").startswith(("https://", "http://"))
                and row.get("retrieved_at") and "license" in row and row.get("source_id") in raw_ids[raw_path]):
            traced += 1
    if traced != len(achievements):
        errors.append(f"source traceability below 100%: {traced}/{len(achievements)}")

    enterprise_ids = {row.get("enterprise_id") for row in enterprises}
    demand_ids = {row.get("demand_id") for row in demands}
    if (None in enterprise_ids or None in demand_ids or len(enterprise_ids) != len(enterprises)
            or len(demand_ids) != len(demands)):
        errors.append("demand or enterprise IDs are missing or duplicated")
    if any(row.get("is_simulated") is not True or not row.get("source_note") for row in demands + enterprises):
        errors.append("a demand or enterprise lacks a simulation flag or source note")
    if any(row.get("legal_name") or not row.get("display_name") for row in enterprises):
        errors.append("an enterprise lacks a display alias or contains a legal name")
    public_seeds = sum(bool(row.get("source_urls")) for row in demands)
    if not 20 <= public_seeds <= 30:
        errors.append(f"expected 20–30 public-source rewrites, got {public_seeds}")
    for row in demands:
        if (row.get("enterprise_id") not in enterprise_ids or row.get("dataset_version") != FULL_VERSION
                or not all(row.get(key) for key in ("title", "pain_point", "expected_solution",
                                                   "technical_metrics", "content_hash"))
                or not 1 <= len(row.get("tech_fields", [])) <= 2
                or not set(row.get("tech_fields", [])) <= TECH_FIELDS
                or not row.get("application_scenarios")
                or not set(row["application_scenarios"]) <= APPLICATION_SCENARIOS
                or not 1 <= len(row.get("cooperation_modes", [])) <= 3
                or not set(row.get("cooperation_modes", [])) <= COOPERATION_MODES
                or type(row.get("required_trl")) is not int or not 1 <= row["required_trl"] <= 9):
            errors.append(f"invalid demand fields or enterprise reference: {row.get('demand_id')}")

    print(json.dumps({
        "dataset_version": FULL_VERSION,
        "achievements": len(achievements),
        "selected_by_tag": dict(counts),
        "required_fields_complete": complete,
        "completeness_rate": completeness,
        "duplicate_count": duplicate_count,
        "duplicate_rate": duplicate_rate,
        "source_traced": traced,
        "demands": len(demands),
        "public_seed_rewrites": public_seeds,
        "enterprises": len(enterprises),
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    if args.version == FULL_VERSION:
        return validate_full_dataset()

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
