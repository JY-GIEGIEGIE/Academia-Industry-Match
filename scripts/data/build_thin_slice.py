#!/usr/bin/env python3
"""Build the v0.1 thin slice from raw OpenAlex snapshots.

What it does:
1. reads data/raw/openalex/<run_id>/*.json
2. reconstructs abstracts, normalizes fields, deduplicates
3. filters by subfield context/topic keywords
4. samples 15 records per main subfield + 5 per auxiliary subfield
5. writes the full cleaned set to data/processed/ (local only)
6. writes a 20-record, abstract-truncated sample to data/samples/ (tracked)

Usage:
    python scripts/data/build_thin_slice.py --run-id thin-20261117
    python scripts/data/build_thin_slice.py --run-id thin-20261117 --version v0.1-thin
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import (
    MANIFEST_DIR,
    MIN_ABSTRACT_CHARS,
    PROCESSED_DIR,
    RAW_DIR,
    SAMPLE_DIR,
    SUBFIELD_SPECS,
    SUBTHEME_RULES,
    TARGET_TOTAL,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TITLE_EXCLUDE = re.compile(
    r"\b(correction|erratum|retraction|retracted|editorial|comment on|reply to)\b",
    re.IGNORECASE,
)
WHITESPACE = re.compile(r"\s+")
HTML_TAG = re.compile(r"<[^>]+>")
CJK = re.compile(r"[一-鿿]")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = HTML_TAG.sub(" ", value)
    value = unicodedata.normalize("NFKC", value)
    value = WHITESPACE.sub(" ", value)
    return value.strip()


def reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions.append((int(index), word))
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def source_id_from_openalex(work: dict) -> str:
    raw = str(work.get("id") or "")
    return raw.rstrip("/").rsplit("/", 1)[-1]


def normalize_language(reported: str, title: str, abstract: str) -> tuple[str, bool]:
    """OpenAlex language labels are noisy; correct obvious mismatches.

    Returns (language, corrected). We only override when the text has a clear
    script signal, so a mixed-language record is left alone.
    """
    text = f"{title} {abstract}"
    cjk_count = len(CJK.findall(text))
    has_cjk = cjk_count > 0
    if reported == "zh" and not has_cjk:
        return "en", True
    if reported in {"en", "unknown"} and cjk_count >= 20:
        return "zh", True
    if reported not in {"en", "zh", "mixed", "unknown"}:
        return "unknown", True
    return reported, False


def normalized_title_key(title: str) -> str:
    value = clean_text(title).lower()
    value = re.sub(r"[^a-z0-9一-鿿]+", "", value)
    return value


def content_hash(title: str, abstract: str, doi: str | None, source_id: str) -> str:
    payload = "|".join([title, abstract, doi or "", source_id])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_work(
    work: dict,
    tag: str,
    lens: str,
    raw_path: Path,
    retrieved_at: str,
    version: str,
) -> dict | None:
    source_id = source_id_from_openalex(work)
    title = clean_text(work.get("title") or work.get("display_name") or "")
    if not title or TITLE_EXCLUDE.search(title):
        return None

    abstract = clean_text(reconstruct_abstract(work.get("abstract_inverted_index")))
    if len(abstract) < MIN_ABSTRACT_CHARS:
        return None

    doi = normalize_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
    year = work.get("publication_year")
    if not isinstance(year, int):
        return None

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    authorships = work.get("authorships") or []

    authors: list[str] = []
    institutions: list[str] = []
    countries: list[str] = []
    for authorship in authorships:
        author = (authorship.get("author") or {}).get("display_name")
        if author:
            authors.append(clean_text(author))
        for institution in authorship.get("institutions") or []:
            name = institution.get("display_name")
            if name:
                institutions.append(clean_text(name))
        for country in authorship.get("countries") or []:
            countries.append(str(country))

    def dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    keywords = dedupe(
        [clean_text(item.get("display_name")) for item in (work.get("keywords") or [])]
    )
    topics = dedupe(
        [clean_text(item.get("display_name")) for item in (work.get("topics") or [])]
    )

    source_url = (
        primary_location.get("landing_page_url")
        or (f"https://doi.org/{doi}" if doi else None)
        or work.get("id")
        or ""
    )
    license_name = primary_location.get("license")
    work_type = str(work.get("type") or "other")
    if work_type not in {"article", "review", "preprint", "patent", "other"}:
        work_type = "other"

    reported_language = str(work.get("language") or "unknown")
    language, language_corrected = normalize_language(reported_language, title, abstract)

    quality_flags: list[str] = ["abstract_reconstructed"]
    if not license_name:
        quality_flags.append("license_missing")
    if not institutions:
        quality_flags.append("no_institutions")
    if not keywords:
        quality_flags.append("no_keywords")
    if reported_language not in {"en", "zh", "mixed", "unknown"}:
        quality_flags.append("language_unknown")
    if language_corrected:
        quality_flags.append("language_metadata_corrected")

    return {
        "achievement_id": f"ach_openalex_{source_id}",
        "source": "openalex",
        "source_id": source_id,
        "doi": doi,
        "patent_no": None,
        "title_original": title,
        "abstract_original": abstract,
        "language": language,
        "publication_year": year,
        "publication_date": work.get("publication_date"),
        "type": work_type,
        "venue": clean_text(source.get("display_name")),
        "authors": authors,
        "institutions": dedupe(institutions),
        "countries": dedupe(countries),
        "keywords": keywords,
        "topics": topics,
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "source_url": source_url,
        "license": license_name,
        "oa_status": open_access.get("oa_status"),
        "retrieved_at": retrieved_at,
        "content_hash": content_hash(title, abstract, doi, source_id),
        "clean_status": "cleaned",
        "review_status": "pending",
        "quality_flags": quality_flags,
        "is_simulated": False,
        "dataset_version": version,
        "query_tag": tag,
        "query_tags": [tag],
        "query_lens": lens,
        "raw_payload_path": str(raw_path.relative_to(PROJECT_ROOT)),
        "selection_score": None,
    }


def merge_duplicate(old: dict, new: dict) -> dict:
    """Keep the record with the longer abstract, merge metadata."""
    keep, other = (new, old) if len(new["abstract_original"]) > len(old["abstract_original"]) else (old, new)
    keep["keywords"] = sorted(set(keep.get("keywords", [])) | set(other.get("keywords", [])))
    keep["topics"] = sorted(set(keep.get("topics", [])) | set(other.get("topics", [])))
    keep["query_tags"] = sorted(set(keep.get("query_tags", [])) | set(other.get("query_tags", [])))
    keep["cited_by_count"] = max(keep.get("cited_by_count", 0), other.get("cited_by_count", 0))
    if not keep.get("doi") and other.get("doi"):
        keep["doi"] = other["doi"]
    return keep


def deduplicate(records: list[dict]) -> tuple[list[dict], int]:
    by_source: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}
    unique: list[dict] = []
    duplicates = 0

    for record in records:
        source_id = record["source_id"]
        doi = record.get("doi")
        title_key = normalized_title_key(record["title_original"])
        existing_index = None
        if source_id in by_source:
            existing_index = by_source[source_id]
        elif doi and doi in by_doi:
            existing_index = by_doi[doi]
        elif title_key and title_key in by_title:
            existing_index = by_title[title_key]

        if existing_index is not None:
            unique[existing_index] = merge_duplicate(unique[existing_index], record)
            duplicates += 1
            continue

        index = len(unique)
        unique.append(record)
        by_source[source_id] = index
        if doi:
            by_doi[doi] = index
        if title_key:
            by_title[title_key] = index

    return unique, duplicates


def score_record(record: dict, spec: dict) -> tuple[float, dict] | None:
    title = record["title_original"].lower()
    abstract = record["abstract_original"].lower()
    keywords = " ".join(record.get("keywords", [])).lower()
    topics = " ".join(record.get("topics", [])).lower()
    blob = " ".join([title, abstract, keywords, topics])

    if any(keyword in title or keyword in abstract for keyword in spec["exclude_keywords"]):
        return None

    context_hits = sum(1 for keyword in spec["context_keywords"] if keyword in blob)
    if context_hits == 0:
        return None

    title_hits = sum(1 for keyword in spec["topic_keywords"] if keyword in title)
    abstract_hits = sum(1 for keyword in spec["topic_keywords"] if keyword in abstract)
    keyword_hits = sum(1 for keyword in spec["topic_keywords"] if keyword in keywords)
    # Require a hit in the title or source keywords, not only a passing mention
    # in the abstract. This keeps e.g. "NMC622 cathode" out of the anode bucket.
    if title_hits + keyword_hits == 0:
        return None

    type_bonus = {"article": 1.0, "review": 0.5}.get(record["type"], 0.0)
    recency = 0.5 * max(0, record["publication_year"] - 2020)
    score = (
        3.0 * title_hits
        + 1.0 * abstract_hits
        + 2.0 * keyword_hits
        + 1.0 * context_hits
        + math.log1p(record["cited_by_count"])
        + recency
        + type_bonus
    )
    return score, {
        "title_hits": title_hits,
        "abstract_hits": abstract_hits,
        "keyword_hits": keyword_hits,
        "context_hits": context_hits,
    }


def record_blob(record: dict) -> str:
    return " ".join(
        [
            record["title_original"],
            record["abstract_original"],
            " ".join(record.get("keywords", [])),
            " ".join(record.get("topics", [])),
        ]
    ).lower()


def matches_subtheme(record: dict, keywords: list[str]) -> bool:
    # Quotas should be filled by papers *about* the material system, not by
    # reviews that merely mention it in the abstract or keyword list.
    title = record["title_original"].lower()
    return any(keyword in title for keyword in keywords)


def select_for_tag(records: list[dict], tag: str, target: int, max_per_year: int = 4) -> list[dict]:
    ranked = sorted(
        records,
        key=lambda item: (-item["selection_score"], -item["cited_by_count"], -item["publication_year"]),
    )
    selected: list[dict] = []
    selected_ids: set[str] = set()
    year_counts: Counter[int] = Counter()

    def try_add(record: dict) -> bool:
        if len(selected) >= target or record["achievement_id"] in selected_ids:
            return False
        if year_counts[record["publication_year"]] >= max_per_year:
            return False
        selected.append(record)
        selected_ids.add(record["achievement_id"])
        year_counts[record["publication_year"]] += 1
        return True

    # First satisfy the material-system quotas, then fill by overall score.
    for keywords, quota in SUBTHEME_RULES.get(tag, {}).values():
        count = 0
        for record in ranked:
            if count >= quota or len(selected) >= target:
                break
            if record["achievement_id"] in selected_ids:
                continue
            if matches_subtheme(record, keywords) and try_add(record):
                count += 1

    for record in ranked:
        if len(selected) >= target:
            break
        try_add(record)

    if len(selected) < target:
        for record in ranked:
            if len(selected) >= target:
                break
            if record["achievement_id"] not in selected_ids:
                selected.append(record)
                selected_ids.add(record["achievement_id"])
    return selected


def truncate_abstract(abstract: str, limit: int = 600) -> str:
    if len(abstract) <= limit:
        return abstract
    return abstract[:limit].rstrip() + "…"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the v0.1 thin slice.")
    parser.add_argument("--run-id", required=True, help="Raw snapshot run id under data/raw/openalex/.")
    parser.add_argument("--version", default="v0.1-thin", help="Dataset version label.")
    parser.add_argument("--target-total", type=int, default=TARGET_TOTAL, help="Total records to select.")
    parser.add_argument("--sample-size", type=int, default=20, help="Sample records for data/samples/.")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()
    raw_run_dir = RAW_DIR / args.run_id
    if not raw_run_dir.exists():
        print(f"Raw run directory not found: {raw_run_dir}", file=sys.stderr)
        return 2

    raw_files = sorted(raw_run_dir.glob("*.json"))
    if not raw_files:
        print(f"No raw JSON files in {raw_run_dir}", file=sys.stderr)
        return 2

    all_records: list[dict] = []
    raw_counts: Counter[str] = Counter()
    raw_results_total = 0
    parse_errors = 0

    for path in raw_files:
        parts = path.stem.split("__")
        tag = parts[0]
        lens = parts[1] if len(parts) > 1 else "relevance"
        if tag not in SUBFIELD_SPECS:
            continue
        retrieved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[warn] cannot read {path}: {exc}", file=sys.stderr)
            parse_errors += 1
            continue

        results = payload.get("results", [])
        raw_results_total += len(results)
        for work in results:
            record = normalize_work(work, tag, lens, path, retrieved_at, args.version)
            if record is not None:
                all_records.append(record)
                raw_counts[tag] += 1

    unique, duplicates = deduplicate(all_records)

    filtered: list[dict] = []
    excluded = 0
    for record in unique:
        spec = SUBFIELD_SPECS[record["query_tag"]]
        scored = score_record(record, spec)
        if scored is None:
            excluded += 1
            continue
        score, hits = scored
        record["selection_score"] = round(score, 4)
        record["selection_hits"] = hits
        filtered.append(record)

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for record in filtered:
        by_tag[record["query_tag"]].append(record)

    selected: list[dict] = []
    selected_ids: set[str] = set()
    shortfalls: dict[str, int] = {}
    for tag, spec in SUBFIELD_SPECS.items():
        chosen = select_for_tag(by_tag.get(tag, []), tag, spec["target"])
        for record in chosen:
            if record["achievement_id"] not in selected_ids:
                selected.append(record)
                selected_ids.add(record["achievement_id"])
        if len(chosen) < spec["target"]:
            shortfalls[tag] = spec["target"] - len(chosen)

    if len(selected) < args.target_total:
        remaining = sorted(
            [record for record in filtered if record["achievement_id"] not in selected_ids],
            key=lambda item: (-item["selection_score"], -item["cited_by_count"]),
        )
        for record in remaining:
            if len(selected) >= args.target_total:
                break
            selected.append(record)
            selected_ids.add(record["achievement_id"])

    selected.sort(key=lambda item: (item["query_tag"], -item["selection_score"], item["title_original"]))

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    processed_jsonl = PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    with processed_jsonl.open("w", encoding="utf-8") as handle:
        for record in selected:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    processed_csv = PROCESSED_DIR / f"achievements_clean_{args.version}.csv"
    write_csv(
        processed_csv,
        selected,
        [
            "achievement_id",
            "query_tag",
            "title_original",
            "publication_year",
            "type",
            "venue",
            "doi",
            "cited_by_count",
            "language",
            "source_url",
            "selection_score",
        ],
    )

    # Build a small, balanced sample for the tracked repo. Abstract is truncated.
    sample_records: list[dict] = []
    sample_seen: set[str] = set()
    for tag in SUBFIELD_SPECS:
        tag_records = sorted(
            [record for record in selected if record["query_tag"] == tag],
            key=lambda item: (-item["selection_score"], item["title_original"]),
        )
        for record in tag_records[:2]:
            if record["achievement_id"] in sample_seen:
                continue
            sample_records.append(record)
            sample_seen.add(record["achievement_id"])
    if len(sample_records) < args.sample_size:
        for record in selected:
            if len(sample_records) >= args.sample_size:
                break
            if record["achievement_id"] not in sample_seen:
                sample_records.append(record)
                sample_seen.add(record["achievement_id"])
    sample_records = sample_records[: args.sample_size]

    sample_rows: list[dict] = []
    for record in sample_records:
        sample = dict(record)
        sample["abstract_original"] = truncate_abstract(record["abstract_original"])
        sample["abstract_truncated"] = len(sample["abstract_original"]) < len(record["abstract_original"])
        sample["sample_note"] = (
            "Repo-safe preview: abstract truncated to <=600 chars; full record stays in data/processed/."
        )
        sample_rows.append(sample)

    sample_jsonl = SAMPLE_DIR / f"achievements_sample_{args.version}.jsonl"
    with sample_jsonl.open("w", encoding="utf-8") as handle:
        for record in sample_rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    sample_csv = SAMPLE_DIR / f"achievements_sample_{args.version}.csv"
    write_csv(
        sample_csv,
        sample_rows,
        [
            "achievement_id",
            "query_tag",
            "title_original",
            "publication_year",
            "type",
            "venue",
            "doi",
            "cited_by_count",
            "language",
            "source_url",
            "abstract_truncated",
        ],
    )

    year_counts = Counter(record["publication_year"] for record in selected)
    language_counts = Counter(record["language"] for record in selected)
    tag_counts = Counter(record["query_tag"] for record in selected)
    abstract_lengths = [len(record["abstract_original"]) for record in selected]

    manifest = {
        "version": args.version,
        "run_id": args.run_id,
        "stage": "build_thin_slice",
        "finished_at": utc_now(),
        "raw_files": len(raw_files),
        "raw_results_total": raw_results_total,
        "normalized_records": sum(raw_counts.values()),
        "normalization_dropped": raw_results_total - sum(raw_counts.values()),
        "raw_records": sum(raw_counts.values()),
        "raw_by_tag": dict(raw_counts),
        "unique_records": len(unique),
        "duplicates_removed": duplicates,
        "excluded_by_filter": excluded,
        "selected": len(selected),
        "selected_by_tag": dict(tag_counts),
        "shortfalls": shortfalls,
        "year_distribution": {str(year): count for year, count in sorted(year_counts.items())},
        "language_distribution": dict(language_counts),
        "abstract_chars": {
            "min": min(abstract_lengths) if abstract_lengths else 0,
            "max": max(abstract_lengths) if abstract_lengths else 0,
            "avg": round(sum(abstract_lengths) / len(abstract_lengths), 1) if abstract_lengths else 0,
        },
        "parse_errors": parse_errors,
        "outputs": {
            "processed_jsonl": str(processed_jsonl.relative_to(PROJECT_ROOT)),
            "processed_csv": str(processed_csv.relative_to(PROJECT_ROOT)),
            "sample_jsonl": str(sample_jsonl.relative_to(PROJECT_ROOT)),
            "sample_csv": str(sample_csv.relative_to(PROJECT_ROOT)),
        },
    }
    manifest_path = MANIFEST_DIR / f"build_thin_slice_{args.version}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Thin slice summary")
    print(
        f"  raw responses: {raw_results_total} | normalized: {manifest['normalized_records']} "
        f"| dropped in normalization: {manifest['normalization_dropped']} | files: {len(raw_files)}"
    )
    print(f"  unique: {len(unique)} | duplicates removed: {duplicates} | filtered out: {excluded}")
    print(f"  selected: {len(selected)} (target {args.target_total})")
    print(f"  by tag: {dict(tag_counts)}")
    if shortfalls:
        print(f"  shortfalls: {shortfalls}")
    print(f"  languages: {dict(language_counts)}")
    print(f"  years: {dict(sorted(year_counts.items()))}")
    print(f"  processed: {processed_jsonl}")
    print(f"  sample: {sample_jsonl}")
    print(f"  manifest: {manifest_path}")
    return 0 if len(selected) >= args.target_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
