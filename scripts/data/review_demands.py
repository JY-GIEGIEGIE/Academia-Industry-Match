"""Read-only checks for a private v0.1 demand handoff; uses the standard library."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import re

DEMAND_FIELDS = (
    "demand_id enterprise_id title pain_point expected_solution technical_metrics "
    "cooperation_modes required_trl tech_fields application_scenarios region status "
    "valid_until is_simulated source_note content_hash dataset_version created_at updated_at"
).split()
ENTERPRISE_FIELDS = (
    "enterprise_id display_name industry size region main_business is_simulated source_note created_at"
).split()
ENUMS = {
    "tech_fields": "cathode_material anode_material electrolyte separator cell_system recycling flow_battery supercapacitor".split(),
    "application_scenarios": "ev_power grid_storage cni_storage residential_storage consumer_electronics e_tool_two_wheeler special recycling_industry".split(),
    "cooperation_modes": "transfer license joint_rd joint_lab tech_service".split(),
    "region": "yangtze_delta pearl_river_delta beijing_tianjin_hebei chengdu_chongqing other any".split(),
    "status": "draft active expired closed".split(),
    "industry": "battery_manufacturing material_manufacturing ev_oem ess_integrator recycling other".split(),
    "size": "large medium small".split(),
}
CONTACT_PATTERN = re.compile(
    r"(?<!\d)1[3-9]\d{9}(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|联系人|联系电话|微信号|身份证"
)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def normalize(value):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", str(value).lower())


def duplicate_groups(records, field):
    groups = defaultdict(list)
    for record in records:
        groups[normalize(record.get(field, ""))].append(record.get("demand_id"))
    return [ids for key, ids in groups.items() if key and len(ids) > 1]


def check_records(records, kind):
    fields = DEMAND_FIELDS if kind == "demand" else ENTERPRISE_FIELDS
    id_field = f"{kind}_id"
    errors, time_issues = [], []
    id_counts = Counter(record.get(id_field) for record in records)
    for record in records:
        record_id = record.get(id_field, "missing_id")
        for field in fields:
            if field not in record or record[field] is None or record[field] == "" or record[field] == []:
                errors.append([record_id, field, "missing_or_empty"])
        if id_counts.get(record_id, 0) > 1:
            errors.append([record_id, id_field, "duplicate_id"])
        if record.get("is_simulated") is not True:
            errors.append([record_id, "is_simulated", "must_be_true"])
        if kind == "demand" and record.get("dataset_version") != "v0.1":
            errors.append([record_id, "dataset_version", "expected_v0.1"])
        enum_fields = ["region", "status"] if kind == "demand" else ["region", "industry", "size"]
        for field in enum_fields:
            if record.get(field) not in ENUMS[field]:
                errors.append([record_id, field, "invalid_enum"])
        if kind == "demand":
            for field, maximum in [("tech_fields", 2), ("application_scenarios", 3), ("cooperation_modes", 3)]:
                values = record.get(field)
                if not isinstance(values, list) or not 1 <= len(values) <= maximum:
                    errors.append([record_id, field, "invalid_array"])
                elif any(value not in ENUMS[field] for value in values):
                    errors.append([record_id, field, "invalid_enum"])
            if type(record.get("required_trl")) is not int or not 1 <= record["required_trl"] <= 9:
                errors.append([record_id, "required_trl", "invalid_integer"])
            metrics = record.get("technical_metrics")
            if not isinstance(metrics, list) or not metrics:
                errors.append([record_id, "technical_metrics", "invalid_array"])
            else:
                for metric in metrics:
                    if not isinstance(metric, dict) or not {"name", "value", "unit"} <= metric.keys():
                        errors.append([record_id, "technical_metrics", "invalid_metric_shape"])
            try:
                date.fromisoformat(record.get("valid_until", ""))
            except (ValueError, TypeError):
                errors.append([record_id, "valid_until", "invalid_date"])
            if not re.fullmatch(r"[0-9a-f]{64}", record.get("content_hash", "")):
                errors.append([record_id, "content_hash", "invalid_sha256_shape"])
        for field in (["created_at", "updated_at"] if kind == "demand" else ["created_at"]):
            value = record.get(field)
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                time_issues.append([record_id, field, "date_only"])
                continue
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                time_issues.append([record_id, field, "invalid_datetime"])
    return errors, time_issues


def audit(demands, enterprises, input_hashes):
    demand_errors, demand_times = check_records(demands, "demand")
    enterprise_errors, enterprise_times = check_records(enterprises, "enterprise")
    enterprise_map = {record.get("enterprise_id"): record for record in enterprises}
    region_differences = []
    for record in demands:
        enterprise = enterprise_map.get(record.get("enterprise_id"))
        if enterprise is None:
            demand_errors.append([record.get("demand_id"), "enterprise_id", "missing_foreign_key"])
        elif record.get("region") != enterprise.get("region") and record.get("region") != "any":
            region_differences.append(record.get("demand_id"))
    candidates = []
    for left, right in combinations(demands, 2):
        title_ratio = SequenceMatcher(None, normalize(left.get("title", "")), normalize(right.get("title", "")), autojunk=False).ratio()
        pain_ratio = SequenceMatcher(None, normalize(left.get("pain_point", "")), normalize(right.get("pain_point", "")), autojunk=False).ratio()
        if max(title_ratio, pain_ratio) >= 0.50:
            candidates.append({"ids": [left.get("demand_id"), right.get("demand_id")], "title_ratio": round(title_ratio, 4), "pain_ratio": round(pain_ratio, 4)})
    public_ids = [record.get("demand_id") for record in demands if record.get("source_urls")]
    blank_units = [record.get("demand_id") for record in demands if any(isinstance(metric, dict) and metric.get("unit") == "" for metric in record.get("technical_metrics", []))]
    instruction_metrics = [record.get("demand_id") for record in demands if isinstance(record.get("technical_metrics"), list) and len(record["technical_metrics"]) == 1 and isinstance(record["technical_metrics"][0], dict) and record["technical_metrics"][0].get("unit") == "" and not re.search(r"\d", str(record["technical_metrics"][0].get("value", "")))]
    hash_matches = sum(sha256("|".join(str(record.get(field, "")) for field in ["title", "pain_point", "expected_solution"]).encode("utf-8")).hexdigest() == record.get("content_hash") for record in demands)
    return {
        "sprint": "2026-11-22", "dataset_version": "v0.1", "taxonomy_version": "v0.1",
        "embedding_model_version": "qwen3.7-text-embedding-flash-1024-v1",
        "method": "stdlib_read_only; SequenceMatcher title_or_pain >= 0.50; no model or source fetch",
        "input_files": ["data/processed/demands_v0.1.jsonl", "data/processed/enterprises_v0.1.jsonl"],
        "input_sha256": input_hashes,
        "counts": {"demands": len(demands), "enterprises": len(enterprises), "public_seed_rewrites": len(public_ids), "team_constructed": len(demands) - len(public_ids)},
        "public_ids": public_ids, "demand_field_errors": demand_errors, "enterprise_field_errors": enterprise_errors,
        "datetime_issues": demand_times + enterprise_times, "region_difference_ids": region_differences,
        "content_hash_matches": hash_matches,
        "field_distribution": {field: sum(field in record.get("tech_fields", []) for record in demands) for field in ENUMS["tech_fields"]},
        "blank_unit_ids": blank_units, "instruction_metric_ids": instruction_metrics,
        "exact_duplicates": {field: duplicate_groups(demands, field) for field in ["title", "pain_point", "content_hash"]},
        "candidate_pairs": sorted(candidates, key=lambda pair: max(pair["title_ratio"], pair["pain_ratio"]), reverse=True),
        "contact_pattern_hits": [record.get("demand_id", record.get("enterprise_id")) for record in demands + enterprises if CONTACT_PATTERN.search(json.dumps(record, ensure_ascii=False))],
        "nonempty_legal_name_ids": [record.get("enterprise_id") for record in enterprises if record.get("legal_name")],
        "limits": ["Datetime issues are listed separately from base field errors.", "Free-text metrics and empty units are not automatically invalid.", "Candidates are not confirmed semantic duplicates.", "Source content and business consistency require manual review."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path, help="Private handoff root containing data/processed/; any local location is accepted.")
    parser.add_argument("--output", required=True, type=Path, help="Statistics JSON destination; never an input data file.")
    args = parser.parse_args()
    inputs = [args.data_root / "data/processed" / name for name in ["demands_v0.1.jsonl", "enterprises_v0.1.jsonl"]]
    if any(args.output.resolve() == path.resolve() for path in inputs):
        parser.error("The output must not overwrite either input file.")
    try:
        demands, enterprises = [read_jsonl(path) for path in inputs]
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read the v0.1 handoff: {error}")
    hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in inputs}
    result = audit(demands, enterprises, hashes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "base_field_errors": len(result["demand_field_errors"]) + len(result["enterprise_field_errors"]), "datetime_issues": len(result["datetime_issues"]), "content_hash_matches": result["content_hash_matches"], "candidate_pairs": len(result["candidate_pairs"])}))
    return int(bool(result["demand_field_errors"] or result["enterprise_field_errors"] or result["datetime_issues"] or result["content_hash_matches"] != len(demands)))


if __name__ == "__main__":
    raise SystemExit(main())
