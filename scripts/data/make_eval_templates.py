#!/usr/bin/env python3
"""Generate retrieval-query and pair-label templates for the thin slice.

Inputs:
    data/processed/achievements_clean_<version>.jsonl
    data/samples/demands_seed_v0.1.jsonl

Outputs:
    data/eval/retrieval_queries_<version>.csv / .jsonl
    data/eval/pair_labels_<version>.csv / .jsonl

The templates intentionally leave relevance labels blank. Annotators fill
0/1/2 after reading the candidate texts, per data/spec/eval_spec_v0.1.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from config import (
    EVAL_DIR,
    EVAL_QUERIES,
    PROCESSED_DIR,
    SAMPLE_DIR,
    SUBFIELD_SPECS,
    TECH_FIELD_TO_QUERY_TAG,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rank_by_citations(records: list[dict]) -> list[dict]:
    return sorted(
        records,
        key=lambda item: (-int(item.get("cited_by_count") or 0), item["achievement_id"]),
    )


# Seed-only helper: map each simulated demand to English technical keywords so
# pair templates prefer on-topic candidates (e.g. LFP for the LFP demand) rather
# than always reusing the most-cited paper in the subfield.
DEMAND_PAIR_KEYWORDS = {
    "dem_001": ["ni-rich", "high-nickel", "single crystal", "single-crystal", "layered oxide", "ncm", "nca"],
    "dem_002": ["lfp", "lithium iron phosphate", "fast charging", "rate capability", "low temperature"],
    "dem_003": ["silicon", "si-c", "silicon-carbon", "silicon anode", "initial coulombic", "expansion"],
    "dem_004": ["hard carbon", "sodium-ion", "na-ion", "sodium ion"],
    "dem_005": ["sulfide", "solid electrolyte", "argyrodite", "li6ps5cl", "ionic conductivity", "air stability"],
    "dem_006": ["oxide", "polymer", "composite electrolyte", "llzo", "peo", "interface"],
    "dem_007": ["separator", "ceramic", "coating", "thermal shrinkage", "polyethylene"],
    "dem_008": ["separator", "pvdf", "pmma", "high voltage", "wettability", "coating"],
    "dem_009": ["thermal runaway", "thermal propagation", "battery pack", "safety", "module"],
    "dem_010": ["thermal management", "fast charging", "liquid cooling", "temperature"],
    "dem_011": ["direct regeneration", "recycling", "ncm", "cathode", "spent"],
    "dem_012": ["hydrometallurgy", "leaching", "recovery", "lithium", "nickel", "cobalt"],
    "dem_013": ["second-life", "second life", "echelon", "soh", "retired", "lfp"],
    "dem_014": ["vanadium", "redox flow", "flow battery", "membrane", "electrolyte", "cost"],
    "dem_015": ["flow battery", "stack", "scale-up", "vanadium", "redox flow"],
    "dem_016": ["supercapacitor", "electrode", "power density", "activated carbon", "graphene"],
    "dem_017": ["supercapacitor", "module", "grid", "frequency", "cycle life"],
    "dem_018": ["solid-state", "interface", "stack pressure", "lithium metal", "dendrite", "sulfide"],
    "dem_019": ["sodium-ion", "na-ion", "hard carbon", "cathode", "grid storage", "low cost"],
    "dem_020": ["lithium cobalt oxide", "licoo2", "high voltage", "4.5 v", "cobalt", "coating"],
}


def demand_match_score(record: dict, keywords: list[str]) -> int:
    blob = " ".join(
        [
            record["title_original"],
            record["abstract_original"],
            " ".join(record.get("keywords", [])),
            " ".join(record.get("topics", [])),
        ]
    ).lower()
    return sum(1 for keyword in keywords if keyword in blob)


def rank_for_demand(
    records: list[dict],
    keywords: list[str],
    used_ids: set[str],
) -> list[dict]:
    return sorted(
        records,
        key=lambda item: (
            -demand_match_score(item, keywords),
            item["achievement_id"] in used_ids,
            -int(item.get("cited_by_count") or 0),
            item["achievement_id"],
        ),
    )


def pick_candidates(
    by_tag: dict[str, list[dict]],
    target_tags: list[str],
    limit: int = 20,
) -> list[dict]:
    per_tag = 12 if len(target_tags) == 1 else 8
    picked: list[dict] = []
    seen: set[str] = set()
    for tag in target_tags:
        for record in rank_by_citations(by_tag.get(tag, []))[:per_tag]:
            if record["achievement_id"] not in seen:
                picked.append(record)
                seen.add(record["achievement_id"])
    if len(picked) < limit:
        other_records: list[dict] = []
        for tag, records in by_tag.items():
            if tag in target_tags:
                continue
            other_records.extend(records)
        for record in rank_by_citations(other_records):
            if len(picked) >= limit:
                break
            if record["achievement_id"] not in seen:
                picked.append(record)
                seen.add(record["achievement_id"])
    return picked[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate evaluation templates.")
    parser.add_argument("--version", default="v0.1-thin", help="Dataset version label.")
    parser.add_argument("--pair-count", type=int, default=50, help="Target number of pair labels.")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    achievements_path = PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    demands_path = SAMPLE_DIR / "demands_seed_v0.1.jsonl"
    if not achievements_path.exists():
        print(f"Missing processed achievements: {achievements_path}", file=sys.stderr)
        return 2
    if not demands_path.exists():
        print(f"Missing demand seeds: {demands_path}", file=sys.stderr)
        return 2

    achievements = load_jsonl(achievements_path)
    demands = load_jsonl(demands_path)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for record in achievements:
        by_tag[record["query_tag"]].append(record)

    query_rows: list[dict] = []
    for query in EVAL_QUERIES:
        candidates = pick_candidates(by_tag, query["target_tags"])
        query_rows.append(
            {
                "query_id": query["query_id"],
                "query_text": query["query_text"],
                "query_language": query["query_language"],
                "query_type": query["query_type"],
                "target_tech_field": ";".join(
                    SUBFIELD_SPECS[tag]["tech_field"] for tag in query["target_tags"]
                ),
                "candidate_achievement_ids": ";".join(
                    record["achievement_id"] for record in candidates
                ),
                "relevant_achievement_ids": "",
                "relevance_grades": "",
                "annotator": "",
                "notes": query["notes"],
            }
        )

    retrieval_csv = EVAL_DIR / f"retrieval_queries_{args.version}.csv"
    retrieval_jsonl = EVAL_DIR / f"retrieval_queries_{args.version}.jsonl"
    write_csv(
        retrieval_csv,
        query_rows,
        [
            "query_id",
            "query_text",
            "query_language",
            "query_type",
            "target_tech_field",
            "candidate_achievement_ids",
            "relevant_achievement_ids",
            "relevance_grades",
            "annotator",
            "notes",
        ],
    )
    write_jsonl(
        retrieval_jsonl,
        [
            {
                **{key: value for key, value in row.items() if key != "candidate_achievement_ids"},
                "candidate_achievement_ids": row["candidate_achievement_ids"].split(";")
                if row["candidate_achievement_ids"]
                else [],
            }
            for row in query_rows
        ],
    )

    pair_rows: list[dict] = []
    other_tags = list(SUBFIELD_SPECS)
    used_ids: set[str] = set()

    for demand in demands:
        keywords = DEMAND_PAIR_KEYWORDS.get(demand["demand_id"], [])
        target_tags: list[str] = []
        for field in demand["tech_fields"]:
            tag = TECH_FIELD_TO_QUERY_TAG.get(field)
            if tag and tag not in target_tags:
                target_tags.append(tag)

        picked: list[dict] = []
        picked_ids: set[str] = set()
        # One candidate per target field first, so a two-field demand gets one
        # anode and one cathode pair instead of two from the primary field.
        for tag in target_tags:
            for record in rank_for_demand(by_tag.get(tag, []), keywords, used_ids):
                if record["achievement_id"] not in picked_ids:
                    picked.append(record)
                    picked_ids.add(record["achievement_id"])
                    break
        if len(picked) < 2:
            pool: list[dict] = []
            for tag in target_tags:
                pool.extend(by_tag.get(tag, []))
            for record in rank_for_demand(pool, keywords, used_ids):
                if len(picked) >= 2:
                    break
                if record["achievement_id"] not in picked_ids:
                    picked.append(record)
                    picked_ids.add(record["achievement_id"])

        for record in picked[:2]:
            pair_rows.append(
                {
                    "pair_id": f"pair_{len(pair_rows) + 1:03d}",
                    "demand_id": demand["demand_id"],
                    "demand_title": demand["title"],
                    "achievement_id": record["achievement_id"],
                    "achievement_title": record["title_original"],
                    "pair_source": "same_field",
                    "hard_negative_type": "none",
                    "relevance_grade": "",
                    "rationale": "",
                    "annotator": "",
                    "adjudication": "",
                }
            )
            used_ids.add(record["achievement_id"])

    # Add one cross-field hard negative for the first 10 demands.
    for demand_index, demand in enumerate(demands[:10]):
        keywords = DEMAND_PAIR_KEYWORDS.get(demand["demand_id"], [])
        target_tags = []
        for field in demand["tech_fields"]:
            tag = TECH_FIELD_TO_QUERY_TAG.get(field)
            if tag and tag not in target_tags:
                target_tags.append(tag)
        candidates_tags = [tag for tag in other_tags if tag not in target_tags and by_tag.get(tag)]
        if not candidates_tags:
            continue
        chosen_tag = candidates_tags[demand_index % len(candidates_tags)]
        record = rank_for_demand(by_tag[chosen_tag], keywords, used_ids)[0]
        pair_rows.append(
            {
                "pair_id": f"pair_{len(pair_rows) + 1:03d}",
                "demand_id": demand["demand_id"],
                "demand_title": demand["title"],
                "achievement_id": record["achievement_id"],
                "achievement_title": record["title_original"],
                "pair_source": "cross_field",
                "hard_negative_type": "cross_field",
                "relevance_grade": "",
                "rationale": "",
                "annotator": "",
                "adjudication": "",
            }
        )
        used_ids.add(record["achievement_id"])

    pair_rows = pair_rows[: args.pair_count]
    pair_csv = EVAL_DIR / f"pair_labels_{args.version}.csv"
    pair_jsonl = EVAL_DIR / f"pair_labels_{args.version}.jsonl"
    write_csv(
        pair_csv,
        pair_rows,
        [
            "pair_id",
            "demand_id",
            "demand_title",
            "achievement_id",
            "achievement_title",
            "pair_source",
            "hard_negative_type",
            "relevance_grade",
            "rationale",
            "annotator",
            "adjudication",
        ],
    )
    write_jsonl(pair_jsonl, pair_rows)

    manifest = {
        "version": args.version,
        "achievements": len(achievements),
        "demands": len(demands),
        "queries": len(query_rows),
        "pairs": len(pair_rows),
        "query_outputs": {
            "csv": str(retrieval_csv.relative_to(PROJECT_ROOT)),
            "jsonl": str(retrieval_jsonl.relative_to(PROJECT_ROOT)),
        },
        "pair_outputs": {
            "csv": str(pair_csv.relative_to(PROJECT_ROOT)),
            "jsonl": str(pair_jsonl.relative_to(PROJECT_ROOT)),
        },
    }
    (EVAL_DIR / f"eval_templates_manifest_{args.version}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Evaluation templates")
    print(f"  achievements: {len(achievements)}")
    print(f"  queries: {len(query_rows)} -> {retrieval_csv}")
    print(f"  pairs: {len(pair_rows)} -> {pair_csv}")
    print("  relevance labels are blank; fill 0/1/2 per data/spec/eval_spec_v0.1.md")
    return 0 if len(pair_rows) == args.pair_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
