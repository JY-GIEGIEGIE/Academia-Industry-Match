#!/usr/bin/env python3
"""Validate and load v0.1 data into PostgreSQL 16 + pgvector.

Uses psycopg 3 (see ``requirements.txt``) for the connection, COPY and
transactions. It validates the JSONL files first, verifies the
private-package hashes when a manifest is present, then imports into the
schema from ``migrations/0001_init.sql``.

Examples:
    python scripts/data/load_db.py --check
    python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate
    python scripts/data/load_db.py --dsn "$DATABASE_URL" --skip-hash --limit 20

The script does not download data. Put the handoff package's
``data/processed/`` files in place first.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

DEFAULT_ACHIEVEMENTS = PROJECT_ROOT / "data/processed/achievements_clean_v0.1-thin.jsonl"
DEFAULT_DEMANDS = PROJECT_ROOT / "data/samples/demands_seed_v0.1.jsonl"
DEFAULT_ENTERPRISES = PROJECT_ROOT / "data/samples/enterprises_seed_v0.1.jsonl"
DEFAULT_EMBEDDINGS = PROJECT_ROOT / "data/processed/embeddings_v0.1-thin.jsonl"
DEFAULT_QUERIES = PROJECT_ROOT / "data/eval/retrieval_queries_v0.1-thin.jsonl"
DEFAULT_PAIRS = PROJECT_ROOT / "data/eval/pair_labels_v0.1-thin.jsonl"
DEFAULT_LABELED = PROJECT_ROOT / "data/processed/achievements_labeled_v0.1-thin.jsonl"
DEFAULT_PROFILES = PROJECT_ROOT / "data/processed/capability_profiles_v0.1-thin.jsonl"
TAXONOMY_PATH = PROJECT_ROOT / "data/spec/taxonomy_v0.1.md"
DEFAULT_MANIFEST = PROJECT_ROOT / "data/manifests/private_data_v0.1-thin.json"
DEFAULT_IMPORT_MANIFEST = PROJECT_ROOT / "data/manifests/import_v0.1.json"
DEFAULT_REPORT = PROJECT_ROOT / "data/manifests/load_report_v0.1.md"

# Keep these in sync with data/spec/data_contract_v0.1.md and taxonomy_v0.1.md.
SOURCES = {"openalex", "arxiv", "cnipa"}
LENSES = {"relevance", "recent", "cited"}
LANGUAGES = {"en", "zh", "mixed", "unknown"}
TYPES = {"article", "review", "preprint", "patent", "other"}
CLEAN_STATUSES = {"raw", "cleaned", "labeled", "embedded", "published"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_review"}
TAG_REVIEW_STATUSES = {"pending", "approved", "rejected"}
DIMENSIONS = {"tech_field", "application_scenario", "cooperation_mode"}
LABEL_DIMENSIONS = DIMENSIONS
PROFILE_LANGUAGES = {"zh", "en"}
TAG_METHODS = {"llm", "rule", "human"}
TEXT_TYPES = {"title_zh", "abstract_zh", "capability_profile_zh", "capability_profile_en"}
TEXT_METHODS = {"original", "machine", "human", "llm"}
IP_STATUSES = {"granted", "pending", "published", "unknown"}
OBJECT_TYPES = {"achievement", "demand", "eval_query"}
EMBEDDING_TEXT_TYPES = {"title", "abstract", "capability_profile", "need_profile"}
INDUSTRIES = {"battery_manufacturing", "material_manufacturing", "ev_oem", "ess_integrator", "recycling", "other"}
SIZES = {"large", "medium", "small"}
REGIONS = {"yangtze_delta", "pearl_river_delta", "beijing_tianjin_hebei", "chengdu_chongqing", "other", "any"}
DEMAND_STATUSES = {"draft", "active", "expired", "closed"}
HARD_NEGATIVE_TYPES = {"cross_field", "same_field_diff_scenario", "same_field_trl_gap", "lexical_trap", "none"}
QUERY_LANGUAGES = {"zh", "en", "mixed"}
QUERY_TYPES = {"zh_business", "en_academic", "cross_lingual", "hard_negative"}
TECH_FIELDS = {
    "cathode_material", "anode_material", "electrolyte", "separator",
    "cell_system", "recycling", "flow_battery", "supercapacitor",
}
SCENARIOS = {
    "ev_power", "grid_storage", "cni_storage", "residential_storage",
    "consumer_electronics", "e_tool_two_wheeler", "special", "recycling_industry",
}
COOPERATION_MODES = {"transfer", "license", "joint_rd", "joint_lab", "tech_service"}
QUALITY_FLAGS = {
    "abstract_reconstructed", "abstract_missing", "abstract_short", "license_missing",
    "no_institutions", "no_keywords", "language_unknown", "language_metadata_corrected",
    "possible_duplicate", "out_of_domain", "title_suspect", "needs_human_review",
    "translated_machine", "profile_machine",
}

ACHIEVEMENT_REQUIRED = [
    "achievement_id", "source", "source_id", "title_original", "abstract_original",
    "language", "publication_year", "type", "source_url", "retrieved_at",
    "content_hash", "clean_status", "review_status", "quality_flags",
    "is_simulated", "dataset_version",
]
ACHIEVEMENT_FIELDS = {
    "achievement_id", "source", "source_id", "doi", "patent_no", "title_original",
    "abstract_original", "language", "publication_year", "publication_date", "type",
    "venue", "authors", "institutions", "countries", "keywords", "topics",
    "cited_by_count", "source_url", "license", "oa_status", "retrieved_at",
    "content_hash", "clean_status", "review_status", "quality_flags",
    "is_simulated", "dataset_version",
}
DEMAND_REQUIRED = [
    "demand_id", "enterprise_id", "title", "pain_point", "expected_solution",
    "technical_metrics", "cooperation_modes", "required_trl", "tech_fields",
    "application_scenarios", "region", "status", "valid_until", "is_simulated",
    "source_note", "content_hash", "dataset_version",
]
ENTERPRISE_REQUIRED = [
    "enterprise_id", "display_name", "industry", "size", "region",
    "main_business", "is_simulated", "source_note",
]

ACHIEVEMENT_COLUMNS = [
    "achievement_id", "source", "source_id", "doi", "patent_no", "title_original",
    "abstract_original", "language", "publication_year", "publication_date", "type",
    "venue", "authors", "institutions", "countries", "keywords", "topics",
    "cited_by_count", "source_url", "license", "oa_status", "retrieved_at",
    "content_hash", "clean_status", "review_status", "quality_flags",
    "is_simulated", "dataset_version",
]
DEMAND_COLUMNS = [
    "demand_id", "enterprise_id", "title", "pain_point", "expected_solution",
    "technical_metrics", "budget_range", "timeline", "cooperation_modes",
    "required_trl", "tech_fields", "application_scenarios", "ip_requirement",
    "region", "status", "valid_until", "is_simulated", "source_note",
    "source_urls", "content_hash", "dataset_version", "created_at", "updated_at",
]
ENTERPRISE_COLUMNS = [
    "enterprise_id", "display_name", "legal_name", "industry", "size", "region",
    "main_business", "tech_base", "resources", "prior_collaboration",
    "is_simulated", "source_note", "created_at",
]
EMBEDDING_COLUMNS = [
    "embedding_id", "object_type", "object_id", "text_type", "model", "dim",
    "text_hash", "vector", "dataset_version",
]
QUERY_COLUMNS = [
    "query_id", "query_text", "query_language", "query_type", "target_tech_field",
    "candidate_achievement_ids", "relevant_achievement_ids", "relevance_grades",
    "annotator", "notes", "dataset_version",
]
PAIR_COLUMNS = [
    "pair_id", "achievement_id", "demand_id", "relevance_grade", "rationale",
    "hard_negative_type", "annotator", "adjudication", "dataset_version",
]
TAG_COLUMNS = [
    "tag_id", "achievement_id", "dimension", "code", "is_primary", "confidence",
    "evidence", "method", "model", "prompt_version", "review_status",
]
EXTRACTION_COLUMNS = [
    "extraction_id", "achievement_id", "material_system", "key_metrics", "process",
    "trl", "trl_confidence", "trl_evidence", "ip_status", "extraction_run_id",
    "model", "prompt_version", "raw_output", "review_status",
]
TEXT_COLUMNS = [
    "text_id", "achievement_id", "text_type", "language", "text", "method",
    "model", "prompt_version", "text_hash",
]


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def redact_dsn(dsn: str) -> str:
    dsn = re.sub(r"(password=)[^\s]+", r"\1***", dsn)
    if "://" not in dsn or "@" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{host}"


def load_jsonl(path: Path | None, label: str, required: bool, v: Validation) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        if required:
            v.error(f"{label}: missing file {path}")
        else:
            v.warn(f"{label}: file not found, skipped ({path})")
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                v.error(f"{label}:{line_number}: invalid JSON ({exc})")
                continue
            if not isinstance(record, dict):
                v.error(f"{label}:{line_number}: expected an object")
                continue
            rows.append(record)
    return rows


def require(record: dict[str, Any], field: str, where: str, v: Validation) -> None:
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        v.error(f"{where}: missing required field {field}")


def check_enum(value: Any, allowed: set[str], field: str, where: str, v: Validation) -> None:
    if value not in allowed:
        v.error(f"{where}: {field}={value!r} not in {sorted(allowed)}")


def check_bool(value: Any, field: str, where: str, v: Validation) -> None:
    if not isinstance(value, bool):
        v.error(f"{where}: {field} must be boolean")


def check_list(value: Any, field: str, where: str, v: Validation) -> None:
    if not isinstance(value, list):
        v.error(f"{where}: {field} must be a list")


def validate_achievements(rows: list[dict[str, Any]], v: Validation) -> set[str]:
    ids: set[str] = set()
    source_ids: set[tuple[str, str]] = set()
    dois: dict[str, str] = {}
    extra_fields: set[str] = set()
    for index, row in enumerate(rows, 1):
        where = f"achievement[{index}] {row.get('achievement_id', '?')}"
        for field in ACHIEVEMENT_REQUIRED:
            require(row, field, where, v)
        check_enum(row.get("source"), SOURCES, "source", where, v)
        check_enum(row.get("language"), LANGUAGES, "language", where, v)
        check_enum(row.get("type"), TYPES, "type", where, v)
        check_enum(row.get("clean_status"), CLEAN_STATUSES, "clean_status", where, v)
        check_enum(row.get("review_status"), REVIEW_STATUSES, "review_status", where, v)
        if row.get("source") and row.get("source_id"):
            key = (str(row["source"]), str(row["source_id"]))
            if key in source_ids:
                v.error(f"{where}: duplicate (source, source_id) {key}")
            source_ids.add(key)
        achievement_id = row.get("achievement_id")
        if achievement_id in ids:
            v.error(f"{where}: duplicate achievement_id")
        if achievement_id:
            ids.add(str(achievement_id))
        doi = row.get("doi")
        if doi:
            normalized = str(doi).lower()
            if normalized in dois and dois[normalized] != achievement_id:
                v.error(f"{where}: duplicate DOI {normalized} (also {dois[normalized]})")
            dois[normalized] = str(achievement_id)
        year = row.get("publication_year")
        if not isinstance(year, int) or not 2000 <= year <= 2026:
            v.error(f"{where}: publication_year={year!r} outside 2000-2026")
        abstract = row.get("abstract_original")
        if isinstance(abstract, str) and len(abstract) < 200:
            v.warn(f"{where}: abstract shorter than 200 chars")
        flags = row.get("quality_flags")
        if not isinstance(flags, list):
            v.error(f"{where}: quality_flags must be a list")
        else:
            for flag in flags:
                if flag not in QUALITY_FLAGS:
                    v.warn(f"{where}: unknown quality flag {flag!r}")
        if "is_simulated" in row:
            check_bool(row["is_simulated"], "is_simulated", where, v)
            if row["is_simulated"]:
                v.warn(f"{where}: achievement marked is_simulated=true")
        extra_fields.update(set(row) - ACHIEVEMENT_FIELDS)
    if extra_fields:
        v.warn("achievements: extra build fields ignored: " + ", ".join(sorted(extra_fields)))
    return ids


def validate_enterprises(rows: list[dict[str, Any]], v: Validation) -> set[str]:
    ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        where = f"enterprise[{index}] {row.get('enterprise_id', '?')}"
        for field in ENTERPRISE_REQUIRED:
            require(row, field, where, v)
        check_enum(row.get("industry"), INDUSTRIES, "industry", where, v)
        check_enum(row.get("size"), SIZES, "size", where, v)
        check_enum(row.get("region"), REGIONS, "region", where, v)
        check_bool(row.get("is_simulated"), "is_simulated", where, v)
        if row.get("is_simulated") is not True:
            v.error(f"{where}: is_simulated must be true")
        enterprise_id = row.get("enterprise_id")
        if enterprise_id in ids:
            v.error(f"{where}: duplicate enterprise_id")
        if enterprise_id:
            ids.add(str(enterprise_id))
    return ids


def validate_demands(rows: list[dict[str, Any]], enterprise_ids: set[str], v: Validation) -> set[str]:
    ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        where = f"demand[{index}] {row.get('demand_id', '?')}"
        for field in DEMAND_REQUIRED:
            require(row, field, where, v)
        enterprise_id = row.get("enterprise_id")
        if enterprise_id and enterprise_id not in enterprise_ids:
            v.error(f"{where}: unknown enterprise_id {enterprise_id}")
        trl = row.get("required_trl")
        if not isinstance(trl, int) or not 1 <= trl <= 9:
            v.error(f"{where}: required_trl={trl!r} outside 1-9")
        check_enum(row.get("region"), REGIONS, "region", where, v)
        check_enum(row.get("status"), DEMAND_STATUSES, "status", where, v)
        check_bool(row.get("is_simulated"), "is_simulated", where, v)
        if row.get("is_simulated") is not True:
            v.error(f"{where}: is_simulated must be true")
        valid_until = row.get("valid_until")
        if valid_until:
            try:
                date.fromisoformat(str(valid_until))
            except ValueError:
                v.error(f"{where}: valid_until is not ISO date ({valid_until!r})")
        for field in ("technical_metrics", "cooperation_modes", "tech_fields", "application_scenarios", "source_urls"):
            check_list(row.get(field, []), field, where, v)
        tech_fields = row.get("tech_fields") or []
        if not isinstance(tech_fields, list) or not 1 <= len(tech_fields) <= 2:
            v.error(f"{where}: tech_fields must contain 1-2 items")
        for code in tech_fields if isinstance(tech_fields, list) else []:
            if code not in TECH_FIELDS:
                v.error(f"{where}: unknown tech_field {code!r}")
        scenarios = row.get("application_scenarios") or []
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 3:
            v.error(f"{where}: application_scenarios must contain 1-3 items")
        for code in scenarios if isinstance(scenarios, list) else []:
            if code not in SCENARIOS:
                v.error(f"{where}: unknown application_scenario {code!r}")
        modes = row.get("cooperation_modes") or []
        if not isinstance(modes, list) or not 1 <= len(modes) <= 3:
            v.error(f"{where}: cooperation_modes must contain 1-3 items")
        for code in modes if isinstance(modes, list) else []:
            if code not in COOPERATION_MODES:
                v.error(f"{where}: unknown cooperation_mode {code!r}")
        metrics = row.get("technical_metrics") or []
        if isinstance(metrics, list):
            for metric in metrics:
                if not isinstance(metric, dict) or not metric.get("name"):
                    v.error(f"{where}: technical_metrics entries need name")
        demand_id = row.get("demand_id")
        if demand_id in ids:
            v.error(f"{where}: duplicate demand_id")
        if demand_id:
            ids.add(str(demand_id))
    return ids


def load_taxonomy_codes() -> dict[str, set[str]]:
    """Parse the code column of each dimension table in taxonomy_v0.1.md."""
    if not TAXONOMY_PATH.exists():
        return {}
    codes: dict[str, set[str]] = {}
    current: str | None = None
    for line in TAXONOMY_PATH.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## \d+\.\s+`([a-z_]+)`", line)
        if heading:
            current = heading.group(1)
            codes.setdefault(current, set())
            continue
        if line.startswith("## "):
            current = None
            continue
        if current and line.startswith("|"):
            cell = line.strip().strip("|").split("|")[0].strip()
            match = re.match(r"^`([a-z0-9_]+)`$", cell)
            if match:
                codes[current].add(match.group(1))
    return codes


def compute_text_hash(text: str) -> str:
    """Use the shared client's normalization so profile and vector hashes match."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.common.llm_client import text_hash

    return text_hash(text)


def validate_embeddings(
    rows: list[dict[str, Any]],
    achievement_ids: set[str],
    demand_ids: set[str],
    query_ids: set[str],
    v: Validation,
) -> None:
    seen: set[tuple[str, str, str, str, str]] = set()
    for index, row in enumerate(rows, 1):
        where = f"embedding[{index}] {row.get('embedding_id', '?')}"
        for field in ("embedding_id", "object_type", "object_id", "text_type", "model", "dim", "text_hash", "vector", "dataset_version"):
            require(row, field, where, v)
        object_type = row.get("object_type")
        if object_type not in OBJECT_TYPES:
            v.error(f"{where}: object_type={object_type!r} invalid")
        object_id = row.get("object_id")
        if object_type == "achievement" and object_id not in achievement_ids:
            v.error(f"{where}: unknown achievement object_id {object_id}")
        if object_type == "demand" and object_id not in demand_ids:
            v.error(f"{where}: unknown demand object_id {object_id}")
        if object_type == "eval_query" and object_id not in query_ids:
            v.error(f"{where}: unknown eval_query object_id {object_id}")
        if row.get("text_type") not in EMBEDDING_TEXT_TYPES:
            v.error(f"{where}: text_type={row.get('text_type')!r} invalid")
        if row.get("dim") != 1024:
            v.error(f"{where}: dim={row.get('dim')!r}, expected 1024")
        vector = row.get("vector")
        if not isinstance(vector, list) or len(vector) != 1024:
            v.error(f"{where}: vector must be a list of 1024 numbers")
        elif not all(isinstance(value, (int, float)) for value in vector):
            v.error(f"{where}: vector contains non-numeric values")
        key = (
            str(row.get("object_type")), str(row.get("object_id")),
            str(row.get("text_type")), str(row.get("model")), str(row.get("text_hash")),
        )
        if key in seen:
            v.error(f"{where}: duplicate embedding key {key}")
        seen.add(key)


def parse_semicolon_list(value: Any) -> list[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return None


def parse_grades(value: Any) -> dict[str, int] | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return {str(key): int(grade) for key, grade in value.items()}
    if isinstance(value, str):
        grades: dict[str, int] = {}
        for part in value.split(";"):
            if ":" not in part:
                continue
            key, grade = part.split(":", 1)
            grades[key.strip()] = int(grade)
        return grades or None
    return None


def validate_eval(
    queries: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    achievement_ids: set[str],
    demand_ids: set[str],
    v: Validation,
) -> set[str]:
    query_ids: set[str] = set()
    missing_version = 0
    for index, row in enumerate(queries, 1):
        where = f"query[{index}] {row.get('query_id', '?')}"
        for field in ("query_id", "query_text", "query_language", "query_type", "target_tech_field", "candidate_achievement_ids"):
            require(row, field, where, v)
        check_enum(row.get("query_language"), QUERY_LANGUAGES, "query_language", where, v)
        check_enum(row.get("query_type"), QUERY_TYPES, "query_type", where, v)
        candidates = row.get("candidate_achievement_ids")
        if not isinstance(candidates, list) or not candidates:
            v.error(f"{where}: candidate_achievement_ids must be a non-empty list")
        else:
            for candidate in candidates:
                if candidate not in achievement_ids:
                    v.error(f"{where}: unknown candidate {candidate}")
        target = row.get("target_tech_field")
        if target:
            for code in str(target).split(";"):
                if code and code not in TECH_FIELDS:
                    v.error(f"{where}: unknown target_tech_field {code!r}")
        grades = parse_grades(row.get("relevance_grades"))
        if grades:
            for key, grade in grades.items():
                if grade not in (0, 1, 2):
                    v.error(f"{where}: relevance_grade {grade} for {key} not 0/1/2")
        if not row.get("dataset_version"):
            missing_version += 1
        query_id = row.get("query_id")
        if query_id in query_ids:
            v.error(f"{where}: duplicate query_id")
        if query_id:
            query_ids.add(str(query_id))
    if missing_version:
        v.warn(f"queries: {missing_version} rows missing dataset_version; defaulting to v0.1-thin")

    pair_ids: set[str] = set()
    missing_pair_version = 0
    empty_grades = 0
    for index, row in enumerate(pairs, 1):
        where = f"pair[{index}] {row.get('pair_id', '?')}"
        for field in ("pair_id", "achievement_id", "demand_id"):
            require(row, field, where, v)
        if row.get("achievement_id") not in achievement_ids:
            v.error(f"{where}: unknown achievement_id {row.get('achievement_id')}")
        if row.get("demand_id") not in demand_ids:
            v.error(f"{where}: unknown demand_id {row.get('demand_id')}")
        grade = row.get("relevance_grade")
        if grade not in ("", None):
            if not isinstance(grade, int) or grade not in (0, 1, 2):
                v.error(f"{where}: relevance_grade={grade!r} not 0/1/2/null")
        else:
            empty_grades += 1
        if row.get("hard_negative_type") not in HARD_NEGATIVE_TYPES and row.get("hard_negative_type") is not None:
            v.error(f"{where}: hard_negative_type={row.get('hard_negative_type')!r} invalid")
        if not row.get("dataset_version"):
            missing_pair_version += 1
        pair_id = row.get("pair_id")
        if pair_id in pair_ids:
            v.error(f"{where}: duplicate pair_id")
        if pair_id:
            pair_ids.add(str(pair_id))
    if missing_pair_version:
        v.warn(f"pairs: {missing_pair_version} rows missing dataset_version; defaulting to v0.1-thin")
    if empty_grades:
        v.warn(f"pairs: {empty_grades} rows have no relevance_grade (annotation pending)")
    return query_ids


def validate_labeled(
    rows: list[dict[str, Any]],
    achievement_ids: set[str],
    taxonomy: dict[str, set[str]],
    v: Validation,
) -> list[dict[str, Any]]:
    """Validate achievements_labeled JSONL; return normalized tag/extraction records."""
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        achievement_id = row.get("achievement_id")
        where = f"labeled[{index}] {achievement_id or '?'}"
        if not achievement_id:
            v.error(f"{where}: missing achievement_id")
            continue
        if achievement_id in seen_ids:
            v.error(f"{where}: duplicate achievement_id")
            continue
        seen_ids.add(achievement_id)
        if achievement_id not in achievement_ids:
            v.error(f"{where}: unknown achievement_id")

        raw_tags = row.get("tags") or []
        if not isinstance(raw_tags, list):
            v.error(f"{where}: tags must be a list")
            raw_tags = []
        tags: list[dict[str, Any]] = []
        tech_field_count = 0
        primary_count = 0
        for tag_index, tag in enumerate(raw_tags, 1):
            tag_where = f"{where} tag[{tag_index}]"
            if not isinstance(tag, dict):
                v.error(f"{tag_where}: must be an object")
                continue
            dimension = tag.get("dimension")
            code = tag.get("code")
            if dimension not in LABEL_DIMENSIONS:
                v.error(f"{tag_where}: dimension={dimension!r} invalid")
                continue
            allowed = taxonomy.get(str(dimension))
            if allowed and code not in allowed:
                v.error(f"{tag_where}: code={code!r} not in taxonomy {dimension}")
                continue
            confidence = tag.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                v.error(f"{tag_where}: confidence must be a number in 0..1")
                continue
            method = tag.get("method")
            if method not in TAG_METHODS:
                v.error(f"{tag_where}: method={method!r} invalid")
                continue
            review = tag.get("review_status") or "pending"
            if review not in TAG_REVIEW_STATUSES:
                v.error(f"{tag_where}: review_status={review!r} invalid (pending/approved/rejected)")
                continue
            is_primary = bool(tag.get("is_primary"))
            if dimension == "tech_field":
                tech_field_count += 1
                if is_primary:
                    primary_count += 1
            elif is_primary:
                v.error(f"{tag_where}: is_primary only allowed on tech_field")
            evidence = tag.get("evidence")
            if not evidence and float(confidence) > 0.4:
                v.warn(f"{tag_where}: no evidence but confidence {confidence}; contract expects <=0.4")
            tags.append({
                "tag_id": f"tag_{achievement_id}_{dimension}_{code}",
                "achievement_id": achievement_id,
                "dimension": dimension,
                "code": code,
                "is_primary": bool(is_primary),
                "confidence": float(confidence),
                "evidence": text_value(evidence),
                "method": method,
                "model": text_value(tag.get("model")),
                "prompt_version": text_value(tag.get("prompt_version")),
                "review_status": review,
            })
        if tech_field_count > 2:
            v.error(f"{where}: {tech_field_count} tech_field tags, max 2")
        if tech_field_count and primary_count != 1:
            v.error(f"{where}: {primary_count} primary tech_field tags, expected exactly 1")
        if not tech_field_count:
            v.warn(f"{where}: no tech_field tag")

        extraction = row.get("extraction")
        normalized_extraction = None
        if extraction is not None:
            if not isinstance(extraction, dict):
                v.error(f"{where}: extraction must be an object or null")
            else:
                trl = extraction.get("trl")
                if trl is not None and (not isinstance(trl, int) or not 1 <= trl <= 9):
                    v.error(f"{where}: trl={trl!r} must be an integer 1..9 or null")
                    trl = None
                trl_evidence = text_value(extraction.get("trl_evidence"))
                if trl is not None and not trl_evidence:
                    v.error(f"{where}: trl={trl} requires trl_evidence")
                trl_confidence = extraction.get("trl_confidence")
                if trl_confidence is not None and (
                    not isinstance(trl_confidence, (int, float)) or not 0 <= float(trl_confidence) <= 1
                ):
                    v.error(f"{where}: trl_confidence must be in 0..1")
                ip_status = extraction.get("ip_status") or "unknown"
                if ip_status not in IP_STATUSES:
                    v.error(f"{where}: ip_status={ip_status!r} invalid")
                model = text_value(extraction.get("model") or row.get("model"))
                prompt_version = text_value(extraction.get("prompt_version") or row.get("prompt_version"))
                if not model:
                    v.error(f"{where}: extraction model is required")
                if not prompt_version:
                    v.error(f"{where}: extraction prompt_version is required")
                run_id = text_value(
                    extraction.get("extraction_run_id") or row.get("extraction_run_id")
                ) or f"extract-{achievement_id}"
                review = extraction.get("review_status") or row.get("review_status") or "pending"
                if review not in TAG_REVIEW_STATUSES:
                    v.error(f"{where}: extraction review_status={review!r} invalid")
                normalized_extraction = {
                    "extraction_id": f"ext_{achievement_id}",
                    "achievement_id": achievement_id,
                    "material_system": text_value(extraction.get("material_system")),
                    "key_metrics": extraction.get("key_metrics") or [],
                    "process": extraction.get("process") or [],
                    "trl": trl,
                    "trl_confidence": float(trl_confidence) if trl_confidence is not None else None,
                    "trl_evidence": trl_evidence,
                    "ip_status": ip_status,
                    "extraction_run_id": run_id,
                    "model": model,
                    "prompt_version": prompt_version,
                    "raw_output": extraction.get("raw_output"),
                    "review_status": review,
                }
        normalized.append({
            "achievement_id": achievement_id,
            "tags": tags,
            "extraction": normalized_extraction,
        })
    return normalized


def validate_profiles(
    rows: list[dict[str, Any]],
    achievement_ids: set[str],
    v: Validation,
) -> list[dict[str, Any]]:
    """Validate capability_profiles JSONL; fill text_id, text_type and text_hash."""
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, 1):
        achievement_id = row.get("achievement_id")
        where = f"profile[{index}] {achievement_id or '?'}"
        if not achievement_id:
            v.error(f"{where}: missing achievement_id")
            continue
        if achievement_id not in achievement_ids:
            v.error(f"{where}: unknown achievement_id")
            continue
        language = row.get("language") or "zh"
        if language not in PROFILE_LANGUAGES:
            v.error(f"{where}: language={language!r} invalid (zh/en)")
            continue
        key = (achievement_id, language)
        if key in seen:
            v.error(f"{where}: duplicate profile for language {language}")
            continue
        seen.add(key)
        text = (row.get("text") or "").strip()
        if not text:
            v.error(f"{where}: empty text")
            continue
        length = len(text)
        if not 150 <= length <= 250:
            v.warn(f"{where}: length {length} outside the 150-250 guidance")
        computed = compute_text_hash(text)
        given = row.get("text_hash")
        if given and given != computed:
            v.warn(f"{where}: text_hash mismatch, recomputed from text")
        method = row.get("method") or "llm"
        if method not in TEXT_METHODS:
            v.error(f"{where}: method={method!r} invalid")
            continue
        text_type = "capability_profile_zh" if language == "zh" else "capability_profile_en"
        normalized.append({
            "text_id": f"txt_{achievement_id}_{text_type}_{language}",
            "achievement_id": achievement_id,
            "text_type": text_type,
            "language": language,
            "text": text,
            "method": method,
            "model": text_value(row.get("model")),
            "prompt_version": text_value(row.get("prompt_version")),
            "text_hash": computed,
        })
    return normalized


def load_all(args: argparse.Namespace, v: Validation) -> dict[str, list[dict[str, Any]]]:
    data = {
        "achievements": load_jsonl(args.achievements, "achievements", True, v),
        "enterprises": load_jsonl(args.enterprises, "enterprises", True, v),
        "demands": load_jsonl(args.demands, "demands", True, v),
        "embeddings": load_jsonl(args.embeddings, "embeddings", False, v),
        "queries": load_jsonl(args.queries, "queries", False, v),
        "pairs": load_jsonl(args.pairs, "pairs", False, v),
        "labeled": load_jsonl(args.labeled, "labeled", False, v),
        "profiles": load_jsonl(args.profiles, "profiles", False, v),
    }
    return data


def validate_all(data: dict[str, list[dict[str, Any]]], v: Validation, args: argparse.Namespace) -> None:
    for key in ("achievements", "demands", "enterprises"):
        if not data[key]:
            v.error(f"{key}: no rows loaded")
    if not data["achievements"]:
        # Every other check resolves achievement ids; stop here instead of
        # emitting hundreds of cascade errors from one missing file.
        return
    if data["queries"] and len(data["queries"]) != 20:
        v.warn(f"queries: {len(data['queries'])} rows, expected 20")
    if data["pairs"] and len(data["pairs"]) != 50:
        v.warn(f"pairs: {len(data['pairs'])} rows, expected 50")
    enterprise_ids = validate_enterprises(data["enterprises"], v)
    achievement_ids = validate_achievements(data["achievements"], v)
    demand_ids = validate_demands(data["demands"], enterprise_ids, v)
    query_ids = validate_eval(data["queries"], data["pairs"], achievement_ids, demand_ids, v)
    validate_embeddings(data["embeddings"], achievement_ids, demand_ids, query_ids, v)
    taxonomy = load_taxonomy_codes()
    if data["labeled"]:
        data["labeled"] = validate_labeled(data["labeled"], achievement_ids, taxonomy, v)
    if data["profiles"]:
        data["profiles"] = validate_profiles(data["profiles"], achievement_ids, v)
    for key in ("achievements", "demands", "enterprises"):
        missing = sum(1 for row in data[key] if not row.get("dataset_version"))
        if missing:
            v.warn(f"{key}: {missing} rows missing dataset_version; defaulting to {args.dataset_version}")


def apply_limit(data: dict[str, list[dict[str, Any]]], args: argparse.Namespace, v: Validation) -> None:
    if not args.limit:
        return
    for key in ("achievements", "demands", "enterprises"):
        data[key] = data[key][: args.limit]
    # Vectors, eval rows, labels and profiles reference ids that may fall
    # outside the truncated slice, so they are skipped entirely.
    data["embeddings"] = []
    data["queries"] = []
    data["pairs"] = []
    data["labeled"] = []
    data["profiles"] = []
    v.warn(f"--limit {args.limit}: core tables limited; vectors, eval, labels and profiles skipped")


def verify_hashes(args: argparse.Namespace, v: Validation) -> None:
    if args.skip_hash:
        v.warn("hash verification skipped by --skip-hash")
        return
    manifest_path = args.manifest
    if manifest_path is None or not manifest_path.exists():
        v.warn(f"hash manifest not found, skipped ({manifest_path})")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        v.error(f"cannot read hash manifest {manifest_path}: {exc}")
        return
    for entry in manifest.get("files", []):
        path = Path(entry.get("path", ""))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            v.warn(f"manifest file missing: {path}")
            continue
        if sha256_file(path) != entry.get("sha256"):
            v.error(f"hash mismatch: {path}")
    package = manifest.get("package", {})
    if args.zip:
        if sha256_file(args.zip) != package.get("sha256"):
            v.error(f"hash mismatch: {args.zip}")
    else:
        v.warn("zip hash not verified; pass --zip to check the handoff package")


def print_check(data: dict[str, list[dict[str, Any]]], v: Validation) -> None:
    print("Load check")
    print(f"  achievements: {len(data['achievements'])}")
    print(f"  demands: {len(data['demands'])} | enterprises: {len(data['enterprises'])}")
    print(f"  embeddings: {len(data['embeddings'])}")
    print(f"  queries: {len(data['queries'])} | pairs: {len(data['pairs'])}")
    print(f"  errors: {len(v.errors)} | warnings: {len(v.warnings)}")
    if v.warnings:
        print("\nWarnings")
        for warning in v.warnings[:20]:
            print(f"  - {warning}")
        if len(v.warnings) > 20:
            print(f"  ... {len(v.warnings) - 20} more")
    if v.errors:
        print("\nErrors")
        for error in v.errors[:30]:
            print(f"  - {error}")
        if len(v.errors) > 30:
            print(f"  ... {len(v.errors) - 30} more")


class Database:
    """Thin psycopg 3 wrapper: one connection, explicit transactions."""

    def __init__(self, dsn: str, connect_timeout: int = 15) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "psycopg is not installed; run: pip install -r requirements.txt"
            ) from exc
        self._psycopg = psycopg
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, connect_timeout=connect_timeout, autocommit=False)

    @property
    def version(self) -> str:
        return f"psycopg {self._psycopg.__version__}"

    def execute(self, sql: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql)

    def scalar(self, sql: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])

    def copy_rows(self, table: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
        quoted = ", ".join(columns)
        sql = f"COPY {table} ({quoted}) FROM STDIN WITH (FORMAT csv, NULL '\\N')"
        payload = build_csv(rows, columns)
        with self.conn.cursor() as cur, cur.copy(sql) as copy:
            copy.write(payload)

    def server_version(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version')")
            row = cur.fetchone()
        return row[0] if row else "unknown"

    def vector_version(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
        return row[0] if row else "missing"

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()


def apply_migrations(db: Database) -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"no migrations found in {MIGRATIONS_DIR}")
    db.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    for path in files:
        print(f"  migration: {path.name}")
        db.execute(path.read_text(encoding="utf-8"))


def json_value(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def bool_value(value: Any) -> str | None:
    if value is None:
        return None
    return "true" if bool(value) else "false"


def vector_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "[" + ",".join(str(float(item)) for item in value) + "]"


def int_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(int(value))


def text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def build_rows(rows: list[dict[str, Any]], columns: list[str], transforms: dict[str, Callable[[Any], Any]], dataset_version: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for column in columns:
            value = row.get(column)
            if column == "dataset_version" and not value:
                value = dataset_version
            if column in transforms:
                value = transforms[column](value)
            item[column] = value
        prepared.append(item)
    return prepared


def build_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(["\\N" if row.get(column) is None else row[column] for column in columns])
    return buffer.getvalue()


def import_table(
    db: Database,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    conflict: str,
    conflict_columns: list[str],
) -> int:
    if not rows:
        return 0
    staging = f"_stg_{table}"
    quoted_columns = ", ".join(columns)
    try:
        db.execute(f"DROP TABLE IF EXISTS {staging}; CREATE UNLOGGED TABLE {staging} (LIKE {table} INCLUDING DEFAULTS);")
        db.copy_rows(staging, columns, rows)
        assignments = [
            f"{column} = EXCLUDED.{column}"
            for column in columns
            if column not in conflict_columns and column not in ("created_at", "updated_at")
        ]
        if "updated_at" in columns:
            assignments.append("updated_at = now()")
        insert_sql = (
            f"INSERT INTO {table} ({quoted_columns}) SELECT {quoted_columns} FROM {staging} "
            f"ON CONFLICT {conflict} DO UPDATE SET {', '.join(assignments)};"
        )
        db.execute(insert_sql)
    finally:
        try:
            db.execute(f"DROP TABLE IF EXISTS {staging};")
        except Exception as cleanup_exc:  # noqa: BLE001 - cleanup must not mask the original error
            print(f"WARN: staging cleanup failed: {cleanup_exc}", file=sys.stderr)
    return len(rows)


def consistency_checks(db: Database) -> dict[str, int]:
    tables = [
        "achievement", "achievement_text", "achievement_tag", "achievement_extraction",
        "embedding", "enterprise", "demand", "demand_tag", "match_score",
        "eval_query", "eval_label", "raw_source_record", "pipeline_run", "dataset_manifest",
    ]
    checks: dict[str, int] = {}
    for table in tables:
        checks[f"rows_{table}"] = db.scalar(f"SELECT count(*) FROM {table};")
    checks["duplicate_doi"] = db.scalar("SELECT count(*) FROM (SELECT lower(doi) FROM achievement WHERE doi IS NOT NULL GROUP BY 1 HAVING count(*) > 1) AS duplicates;",
    )
    checks["orphan_embeddings"] = db.scalar("""SELECT count(*) FROM embedding e
           WHERE (e.object_type = 'achievement' AND NOT EXISTS (SELECT 1 FROM achievement a WHERE a.achievement_id = e.object_id))
              OR (e.object_type = 'demand' AND NOT EXISTS (SELECT 1 FROM demand d WHERE d.demand_id = e.object_id))
              OR (e.object_type = 'eval_query' AND NOT EXISTS (SELECT 1 FROM eval_query q WHERE q.query_id = e.object_id));""",
    )
    checks["vector_dim_mismatch"] = db.scalar('SELECT count(*) FROM embedding WHERE vector_dims("vector") <> 1024;',
    )
    checks["fk_demand_enterprise"] = db.scalar("SELECT count(*) FROM demand d LEFT JOIN enterprise e ON e.enterprise_id = d.enterprise_id WHERE e.enterprise_id IS NULL;",
    )
    checks["fk_eval_label_achievement"] = db.scalar("SELECT count(*) FROM eval_label l LEFT JOIN achievement a ON a.achievement_id = l.achievement_id WHERE a.achievement_id IS NULL;",
    )
    checks["fk_eval_label_demand"] = db.scalar("SELECT count(*) FROM eval_label l LEFT JOIN demand d ON d.demand_id = l.demand_id WHERE d.demand_id IS NULL;",
    )
    checks["simulated_demand_false"] = db.scalar("SELECT count(*) FROM demand WHERE is_simulated IS NOT TRUE;")
    checks["simulated_enterprise_false"] = db.scalar("SELECT count(*) FROM enterprise WHERE is_simulated IS NOT TRUE;")
    checks["achievements_without_primary_tech_field"] = db.scalar(
        """SELECT count(*) FROM achievement a
           WHERE NOT EXISTS (
               SELECT 1 FROM achievement_tag t
               WHERE t.achievement_id = a.achievement_id AND t.dimension = 'tech_field' AND t.is_primary
           );"""
    )
    checks["achievements_without_profile"] = db.scalar(
        """SELECT count(*) FROM achievement a
           WHERE NOT EXISTS (
               SELECT 1 FROM achievement_text t
               WHERE t.achievement_id = a.achievement_id AND t.text_type LIKE 'capability_profile%'
           );"""
    )
    checks["achievements_without_embedding"] = db.scalar(
        """SELECT count(*) FROM achievement a
           WHERE NOT EXISTS (
               SELECT 1 FROM embedding e
               WHERE e.object_type = 'achievement' AND e.object_id = a.achievement_id
                 AND e.text_type = 'capability_profile'
           );"""
    )
    checks["demands_without_embedding"] = db.scalar(
        """SELECT count(*) FROM demand d
           WHERE NOT EXISTS (
               SELECT 1 FROM embedding e
               WHERE e.object_type = 'demand' AND e.object_id = d.demand_id
                 AND e.text_type = 'need_profile'
           );"""
    )
    checks["embedding_text_hash_mismatch"] = db.scalar(
        """SELECT count(*) FROM embedding e
           JOIN achievement_text t
             ON t.achievement_id = e.object_id
            AND t.text_type = 'capability_profile_zh'
           WHERE e.object_type = 'achievement'
             AND e.text_type = 'capability_profile'
             AND e.text_hash <> t.text_hash;"""
    )
    return checks


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout.strip() or None
    except OSError:
        return None


def source_files(data: dict[str, list[dict[str, Any]]], args: argparse.Namespace) -> list[dict[str, Any]]:
    paths = {
        "achievements": args.achievements,
        "demands": args.demands,
        "enterprises": args.enterprises,
        "embeddings": args.embeddings,
        "queries": args.queries,
        "pairs": args.pairs,
        "labeled": args.labeled,
        "profiles": args.profiles,
    }
    files: list[dict[str, Any]] = []
    for key, path in paths.items():
        if path is None or not path.exists():
            continue
        try:
            relative = path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            relative = str(path)
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "rows": len(data.get(key, [])),
        })
    return files


def import_all(db: Database, data: dict[str, list[dict[str, Any]]], args: argparse.Namespace) -> dict[str, int]:
    counts: dict[str, int] = {}

    enterprise_transforms = {
        "legal_name": text_value,
        "tech_base": text_value,
        "resources": text_value,
        "prior_collaboration": text_value,
        "created_at": lambda value: value or iso(now_utc()),
    }
    enterprises = build_rows(data["enterprises"], ENTERPRISE_COLUMNS, enterprise_transforms, args.dataset_version)
    counts["enterprise"] = import_table(db, "enterprise", ENTERPRISE_COLUMNS, enterprises, "(enterprise_id)", ["enterprise_id"])

    achievement_transforms = {
        "authors": json_value, "institutions": json_value, "countries": json_value,
        "keywords": json_value, "topics": json_value, "quality_flags": json_value,
        "is_simulated": bool_value,
    }
    achievement_transforms.update({
        "doi": lambda value: str(value).lower() if value else None,
        "patent_no": text_value,
        "publication_date": text_value,
        "venue": text_value,
        "license": text_value,
        "oa_status": text_value,
        "cited_by_count": int_value,
    })
    achievements = build_rows(data["achievements"], ACHIEVEMENT_COLUMNS, achievement_transforms, args.dataset_version)
    counts["achievement"] = import_table(db, "achievement", ACHIEVEMENT_COLUMNS, achievements, "(achievement_id)", ["achievement_id"])

    demand_transforms = {
        "technical_metrics": json_value, "cooperation_modes": json_value,
        "tech_fields": json_value, "application_scenarios": json_value,
        "source_urls": json_value, "is_simulated": bool_value,
        "budget_range": text_value, "timeline": text_value, "ip_requirement": text_value,
        "created_at": lambda value: value or iso(now_utc()),
        "updated_at": lambda value: value or iso(now_utc()),
    }
    demands = build_rows(data["demands"], DEMAND_COLUMNS, demand_transforms, args.dataset_version)
    counts["demand"] = import_table(db, "demand", DEMAND_COLUMNS, demands, "(demand_id)", ["demand_id"])

    embedding_transforms = {"vector": vector_value}
    embeddings = build_rows(data["embeddings"], EMBEDDING_COLUMNS, embedding_transforms, args.dataset_version)
    counts["embedding"] = import_table(
        db, "embedding", EMBEDDING_COLUMNS, embeddings,
        "(object_type, object_id, text_type, model, text_hash)",
        ["embedding_id", "object_type", "object_id", "text_type", "model", "text_hash"],
    )

    query_transforms = {
        "candidate_achievement_ids": json_value,
        "relevant_achievement_ids": json_value,
        "relevance_grades": json_value,
        "annotator": text_value,
        "notes": text_value,
    }
    queries = build_rows(data["queries"], QUERY_COLUMNS, query_transforms, args.dataset_version)
    counts["eval_query"] = import_table(db, "eval_query", QUERY_COLUMNS, queries, "(query_id)", ["query_id"])

    pair_transforms = {
        "relevance_grade": int_value,
        "rationale": text_value,
        "hard_negative_type": text_value,
        "annotator": text_value,
        "adjudication": text_value,
    }
    pairs = build_rows(data["pairs"], PAIR_COLUMNS, pair_transforms, args.dataset_version)
    counts["eval_label"] = import_table(db, "eval_label", PAIR_COLUMNS, pairs, "(pair_id)", ["pair_id"])

    if data.get("labeled"):
        counts.update(import_labeled(db, data["labeled"], args))
    if data.get("profiles"):
        counts.update(import_profiles(db, data["profiles"], args))

    return counts


def ensure_pipeline_run(db: Database, run_id: str, stage: str, args: argparse.Namespace, note: str) -> None:
    """Create a placeholder pipeline_run so extraction FK constraints hold."""
    config = json.dumps({"source": "load_db.py", "note": note}, ensure_ascii=False)
    sql = (
        "INSERT INTO pipeline_run (run_id, stage, started_at, finished_at, status, input_count, output_count, config, git_commit, dataset_version) "
        f"VALUES ({sql_literal(run_id)}, {sql_literal(stage)}, now(), now(), 'partial', 0, 0, "
        f"{sql_literal(config)}::jsonb, {sql_literal(git_commit())}, {sql_literal(args.dataset_version)}) "
        "ON CONFLICT (run_id) DO NOTHING;"
    )
    db.execute(sql)


def delete_for_achievements(
    db: Database,
    table: str,
    achievement_ids: set[str],
    extra_where: str = "",
) -> int:
    """Delete child rows for these achievements so a re-run replaces them cleanly."""
    ids = sorted(achievement_ids)
    if not ids:
        return 0
    deleted = 0
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        literals = ", ".join(sql_literal(value) for value in chunk)
        where = f"achievement_id IN ({literals})"
        if extra_where:
            where += f" AND {extra_where}"
        deleted += db.scalar(
            f"WITH removed AS (DELETE FROM {table} WHERE {where} RETURNING 1) SELECT count(*) FROM removed;"
        )
    return deleted


def import_labeled(db: Database, labeled: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, int]:
    counts: dict[str, int] = {}
    tag_rows = [tag for record in labeled for tag in record["tags"]]
    extraction_rows = [record["extraction"] for record in labeled if record["extraction"]]
    achievement_ids = {record["achievement_id"] for record in labeled}
    replaced_tags = delete_for_achievements(db, "achievement_tag", achievement_ids)
    replaced_extractions = delete_for_achievements(db, "achievement_extraction", achievement_ids)
    if replaced_tags or replaced_extractions:
        print(f"  replaced {replaced_tags} tag rows and {replaced_extractions} extraction rows")
    for run_id in sorted({row["extraction_run_id"] for row in extraction_rows}):
        ensure_pipeline_run(db, run_id, "extract", args, "synthesized by load_db.py for extraction FK")
    if tag_rows:
        prepared = build_rows(
            tag_rows, TAG_COLUMNS,
            {"is_primary": bool_value, "evidence": text_value, "model": text_value, "prompt_version": text_value},
            args.dataset_version,
        )
        counts["achievement_tag"] = import_table(
            db, "achievement_tag", TAG_COLUMNS, prepared,
            "(achievement_id, dimension, code)", ["achievement_id", "dimension", "code"],
        )
    if extraction_rows:
        prepared = build_rows(
            extraction_rows, EXTRACTION_COLUMNS,
            {"key_metrics": json_value, "process": json_value, "raw_output": json_value, "material_system": text_value},
            args.dataset_version,
        )
        counts["achievement_extraction"] = import_table(
            db, "achievement_extraction", EXTRACTION_COLUMNS, prepared,
            "(achievement_id)", ["achievement_id"],
        )
    return counts


def import_profiles(db: Database, profiles: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, int]:
    if not profiles:
        return {}
    replaced = delete_for_achievements(
        db, "achievement_text", {row["achievement_id"] for row in profiles},
        "text_type LIKE 'capability_profile%'",
    )
    if replaced:
        print(f"  replaced {replaced} profile rows")
    prepared = build_rows(
        profiles, TEXT_COLUMNS,
        {"model": text_value, "prompt_version": text_value},
        args.dataset_version,
    )
    return {
        "achievement_text": import_table(
            db, "achievement_text", TEXT_COLUMNS, prepared,
            "(achievement_id, text_type, language)", ["achievement_id", "text_type", "language"],
        )
    }


def insert_pipeline_run(
    db: Database,
    run_id: str,
    started: datetime,
    finished: datetime,
    status: str,
    input_count: int,
    output_count: int,
    args: argparse.Namespace,
) -> None:
    config = json.dumps({"source": "load_db.py", "limit": args.limit}, ensure_ascii=False)
    sql = (
        "INSERT INTO pipeline_run (run_id, stage, started_at, finished_at, status, input_count, output_count, config, git_commit, dataset_version, log_path) "
        f"VALUES ({sql_literal(run_id)}, 'load', {sql_literal(iso(started))}::timestamptz, {sql_literal(iso(finished))}::timestamptz, "
        f"{sql_literal(status)}, {input_count}, {output_count}, {sql_literal(config)}::jsonb, {sql_literal(git_commit())}, "
        f"{sql_literal(args.dataset_version)}, {sql_literal(str(args.report))}) "
        "ON CONFLICT (run_id) DO UPDATE SET finished_at = EXCLUDED.finished_at, status = EXCLUDED.status, "
        "output_count = EXCLUDED.output_count, config = EXCLUDED.config;"
    )
    db.execute(sql)


def update_pipeline_run_status(db: Database, run_id: str, status: str, finished: datetime) -> None:
    sql = (
        f"UPDATE pipeline_run SET status = {sql_literal(status)}, finished_at = {sql_literal(iso(finished))}::timestamptz "
        f"WHERE run_id = {sql_literal(run_id)};"
    )
    db.execute(sql)


def insert_dataset_manifest(
    db: Database,
    run_id: str,
    counts: dict[str, int],
    data: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
    notes: str,
) -> None:
    manifest_id = "manifest-" + run_id
    files = source_files(data, args)
    hashes = {entry["path"]: entry["sha256"] for entry in files}
    sql = (
        "INSERT INTO dataset_manifest (manifest_id, run_id, dataset_version, taxonomy_version, embedding_model, source, counts, hashes, notes) "
        f"VALUES ({sql_literal(manifest_id)}, {sql_literal(run_id)}, {sql_literal(args.dataset_version)}, 'v0.1', "
        f"{sql_literal(args.embedding_model_version)}, 'load_db.py', {sql_literal(json.dumps(counts, ensure_ascii=False))}::jsonb, "
        f"{sql_literal(json.dumps(hashes, ensure_ascii=False))}::jsonb, {sql_literal(notes)}) "
        "ON CONFLICT (manifest_id) DO UPDATE SET counts = EXCLUDED.counts, hashes = EXCLUDED.hashes, notes = EXCLUDED.notes;"
    )
    db.execute(sql)


def write_report(
    path: Path,
    run_id: str,
    dsn: str,
    started: datetime,
    finished: datetime,
    status: str,
    counts: dict[str, int],
    checks: dict[str, int],
    warnings: list[str],
    errors: list[str],
    args: argparse.Namespace,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Load report v0.1",
        "",
        f"- run_id: `{run_id}`",
        f"- status: `{status}`",
        f"- dsn: `{redact_dsn(dsn)}`",
        f"- dataset_version: `{args.dataset_version}`",
        "- taxonomy_version: `v0.1`",
        f"- embedding_model_version: `{args.embedding_model_version or 'null'}`",
        f"- started_at: `{iso(started)}`",
        f"- finished_at: `{iso(finished)}`",
        "",
        "## Counts",
        "",
        "| table | rows |",
        "| --- | ---: |",
    ]
    for table, value in counts.items():
        lines.append(f"| `{table}` | {value} |")
    lines += [
        "",
        "## Checks",
        "",
        "| check | value | result |",
        "| --- | ---: | --- |",
    ]
    hard_zero = {
        "duplicate_doi", "orphan_embeddings", "vector_dim_mismatch",
        "fk_demand_enterprise", "fk_eval_label_achievement", "fk_eval_label_demand",
        "simulated_demand_false", "simulated_enterprise_false",
    }
    info_checks = {
        "achievements_without_primary_tech_field",
        "achievements_without_profile",
        "embedding_text_hash_mismatch",
        "achievements_without_embedding",
        "demands_without_embedding",
    }
    for check, value in checks.items():
        if check in info_checks:
            result = "INFO"
        else:
            result = "OK" if (value == 0 or check not in hard_zero) else "CHECK"
        lines.append(f"| `{check}` | {value} | {result} |")
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {warning}" for warning in warnings]
    if errors:
        lines += ["", "## Errors", ""] + [f"- {error}" for error in errors]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_import_manifest(
    path: Path,
    run_id: str,
    status: str,
    started: datetime,
    finished: datetime,
    data: dict[str, list[dict[str, Any]]],
    counts: dict[str, int],
    checks: dict[str, int],
    warnings: list[str],
    errors: list[str],
    args: argparse.Namespace,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "stage": "load",
        "status": status,
        "started_at": iso(started),
        "finished_at": iso(finished),
        "input_count": sum(len(rows) for rows in data.values()),
        "output_count": sum(counts.values()),
        "counts": counts,
        "checks": checks,
        "dataset_version": args.dataset_version,
        "taxonomy_version": "v0.1",
        "embedding_model_version": args.embedding_model_version,
        "git_commit": git_commit(),
        "source_files": source_files(data, args),
        "warnings": warnings,
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_data_paths(args: argparse.Namespace) -> None:
    """Pick -thin or full paths from --dataset-version when a path is not given."""
    thin = args.dataset_version == "v0.1-thin"
    processed = PROJECT_ROOT / "data/processed"
    samples = PROJECT_ROOT / "data/samples"
    mapping = {
        "achievements": (
            processed / "achievements_clean_v0.1-thin.jsonl",
            processed / "achievements_clean_v0.1.jsonl",
        ),
        "labeled": (
            processed / "achievements_labeled_v0.1-thin.jsonl",
            processed / "achievements_labeled_v0.1.jsonl",
        ),
        "profiles": (
            processed / "capability_profiles_v0.1-thin.jsonl",
            processed / "capability_profiles_v0.1.jsonl",
        ),
        "embeddings": (
            processed / "embeddings_v0.1-thin.jsonl",
            processed / "embeddings_v0.1.jsonl",
        ),
        "demands": (
            samples / "demands_seed_v0.1.jsonl",
            processed / "demands_v0.1.jsonl",
        ),
        "enterprises": (
            samples / "enterprises_seed_v0.1.jsonl",
            processed / "enterprises_v0.1.jsonl",
        ),
    }
    for attribute, (thin_path, full_path) in mapping.items():
        if getattr(args, attribute) is None:
            setattr(args, attribute, thin_path if thin else full_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and load v0.1 data into PostgreSQL 16 + pgvector.")
    parser.add_argument("--check", action="store_true", help="validate files only; no database required")
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="PostgreSQL DSN (default: DATABASE_URL)")
    parser.add_argument("--migrate-only", action="store_true", help="apply migrations and exit")
    parser.add_argument("--connect-timeout", type=int, default=15, help="database connect timeout in seconds")
    parser.add_argument("--achievements", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--demands", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--enterprises", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--embeddings", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--labeled", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--profiles", type=Path, default=None, help="default: depends on --dataset-version")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--zip", type=Path, default=None, help="optional handoff zip to verify")
    parser.add_argument("--skip-hash", action="store_true")
    parser.add_argument("--migrate", action="store_true", help="apply migrations/*.sql before loading")
    parser.add_argument("--limit", type=int, default=None, help="limit rows per dataset for a smoke test")
    parser.add_argument("--dataset-version", default="v0.1-thin")
    parser.add_argument("--embedding-model-version", default=None)
    parser.add_argument("--import-manifest", type=Path, default=DEFAULT_IMPORT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.check and args.migrate:
        parser.error("--check cannot be combined with --migrate")
    if args.migrate_only and not args.migrate:
        parser.error("--migrate-only requires --migrate")
    resolve_data_paths(args)
    return args


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()

    if args.migrate_only:
        # Migration must work on a fresh clone with no data files present,
        # so run it before any JSONL is read.
        if not args.dsn:
            print("ERROR: --dsn or DATABASE_URL is required for import", file=sys.stderr)
            return 2
        try:
            db = Database(args.dsn, connect_timeout=args.connect_timeout)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"ERROR: cannot connect: {redact_dsn(str(exc))}", file=sys.stderr)
            return 2
        try:
            print("Applying migrations")
            apply_migrations(db)
            db.commit()
            print("  migrations applied")
            return 0
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            try:
                db.rollback()
            except Exception as rollback_exc:  # noqa: BLE001 - keep the original error
                print(f"WARN: rollback failed: {rollback_exc}", file=sys.stderr)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            db.close()

    v = Validation()
    data = load_all(args, v)
    validate_all(data, v, args)
    verify_hashes(args, v)

    if args.check:
        if args.limit:
            v.warn("--limit is ignored in --check; full files are validated")
        print_check(data, v)
        return 0 if not v.errors else 1

    if v.errors:
        print_check(data, v)
        return 1

    apply_limit(data, args, v)

    if not args.dsn:
        print("ERROR: --dsn or DATABASE_URL is required for import", file=sys.stderr)
        return 2
    try:
        db = Database(args.dsn, connect_timeout=args.connect_timeout)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: cannot connect: {redact_dsn(str(exc))}", file=sys.stderr)
        return 2

    started = now_utc()
    run_id = "load-" + started.strftime("%Y%m%dT%H%M%S%fZ")
    try:
        if args.migrate:
            print("Applying migrations")
            apply_migrations(db)
        print(f"  server: PostgreSQL {db.server_version()} / pgvector {db.vector_version()}")
        print("Importing")
        counts = import_all(db, data, args)
        finished = now_utc()
        input_count = sum(len(rows) for rows in data.values())
        output_count = sum(counts.values())
        insert_pipeline_run(db, run_id, started, finished, "running", input_count, output_count, args)
        insert_dataset_manifest(
            db, run_id, counts, data, args,
            notes=f"input={input_count}; output={output_count}; warnings={len(v.warnings)}",
        )
        checks = consistency_checks(db)
        hard_zero = {
            "duplicate_doi", "orphan_embeddings", "vector_dim_mismatch",
            "fk_demand_enterprise", "fk_eval_label_achievement", "fk_eval_label_demand",
            "simulated_demand_false", "simulated_enterprise_false",
        }
        status = "success" if all(checks.get(name, 0) == 0 for name in hard_zero) else "partial"
        update_pipeline_run_status(db, run_id, status, finished)
        db.commit()
        write_report(args.report, run_id, args.dsn, started, finished, status, counts, checks, v.warnings, v.errors, args)
        write_import_manifest(args.import_manifest, run_id, status, started, finished, data, counts, checks, v.warnings, v.errors, args)
        print(f"  imported: {counts}")
        print(f"  status: {status}")
        print(f"  report: {args.report}")
        print(f"  manifest: {args.import_manifest}")
        return 0 if status == "success" else 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        finished = now_utc()
        try:
            db.rollback()
        except Exception as rollback_exc:  # noqa: BLE001 - keep the original error
            print(f"WARN: rollback failed: {rollback_exc}", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        try:
            write_report(args.report, run_id, args.dsn, started, finished, "failed", {}, {}, v.warnings, [str(exc)], args)
            write_import_manifest(
                args.import_manifest, run_id, "failed", started, finished,
                data, {}, {}, v.warnings, [str(exc)], args,
            )
        except OSError:
            pass
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
