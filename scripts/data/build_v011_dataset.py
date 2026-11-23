#!/usr/bin/env python3
"""Build the v0.1.1 data-delivery files from the accepted v0.1 snapshot.

This script is intentionally file-only: it does not write PostgreSQL and does
not modify the v0.1 files. It applies the PM-approved corrections:

  - S-07: seven P1 demand patches from demands_review_v0.1.md
  - 50 date-only datetime values -> ISO datetime at 00:00:00Z
  - W4401101842: add electrolyte primary tag
  - TRL=null -> needs_review (including previously pending rows)
  - profile >250 chars is accepted; only missing/<150 chars flags review
  - version fields -> v0.1.1

Embeddings are regenerated separately by embed.py --version v0.1.1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
EVAL = ROOT / "data" / "eval"
MANIFEST = ROOT / "data" / "manifests"
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CORRECTION_TIME = "2026-11-23T00:00:00Z"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(row: dict) -> str:
    raw = "|".join(str(row.get(k, "")) for k in ("title", "pain_point", "expected_solution"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


S07_PATCHES: dict[str, dict] = {
    "dem_021": {
        "title": "干法正极极片用 PTFE 粘结剂一致性验证",
        "tech_fields": ["cell_system"],
        "pain_point": "现用 PTFE 在厚正极极片中形成的纤维网络不均匀，批次差异会放大面密度和剥离力波动，影响客户对极片稳定性的验证。",
        "expected_solution": "希望联合研发方提供可重复制样的候选 PTFE 粘结剂，在我方正极粉体和固定制片工艺下与现用品比较，交付批次检测记录、极片样件及工艺适配建议；本需求不要求我方自行建设 PTFE 聚合产线。",
        "technical_metrics": [
            {
                "name": "极片面密度偏差",
                "value": "固定配方、添加量和制片工艺，逐批报告分布，并按现用极片的内部放行限值判定；限值须在试验前书面确认。",
                "unit": "%",
            },
            {
                "name": "极片剥离力",
                "value": "固定厚度、剥离角度和速度，候选样品结果不得低于现用品对照，并提交原始曲线。",
                "unit": "N/m",
            },
        ],
        "source_note": "参考公开榜单 SM2026H131 的干法电极 PTFE 方向改写为极片适配验证需求。团队构造，不对应真实企业或真实需求；企业能力、验收条件与最低接入 TRL 均为模拟设定。",
    },
    "dem_032": {
        "title": "固态复合极片导锂粘结剂适配验证",
        "tech_fields": ["cell_system"],
        "pain_point": "现有固态复合极片循环后容易失去颗粒接触，阻抗上升，粘结强度也随之下降；仅提高粘结力难以同时维持离子传输。",
        "expected_solution": "希望研发方提供可重复制样的柔性导锂粘结剂，在我方复合膜与极片试制条件下和常规粘结剂比较，交付极片样件、循环前后阻抗与粘附记录及适配建议；交付对象是粘结剂和复合极片。",
        "technical_metrics": [
            {
                "name": "复合极片面阻抗",
                "value": "固定膜厚、载量、温度及压紧条件，比较循环前后变化；候选方案的阻抗增幅不得高于常规粘结剂对照。",
                "unit": "Ω·cm²",
            },
            {
                "name": "循环后剥离力",
                "value": "使用同批极片、相同循环程序与剥离方法，循环后剥离力不得低于常规粘结剂对照；提交原始测试记录。",
                "unit": "N/m",
            },
        ],
    },
    "dem_036": {
        "tech_fields": ["recycling", "anode_material"],
        "pain_point": "合作方提供的废石墨负极原料在表面和结构上存在损伤，直接回用时首效与倍率波动，难以稳定替代同规格新料。",
        "expected_solution": "由合作方提供已完成安全预处理的再生原料，我方联合研发团队比较结构修复与表面处理路线，在相同负极制样条件下核验首效和倍率，交付再生粉体样品、检测记录及可回用条件；不将电池拆解产线作为我方现有能力。",
        "technical_metrics": [
            {
                "name": "再生石墨首次库伦效率",
                "value": "固定面载量、制样体系、温度和首圈倍率，分别报告再生料与同规格新料结果，按试验前确认的内部替代料放行限值判定。",
                "unit": "%",
            }
        ],
    },
    "dem_052": {
        "enterprise_id": "ent_002",
        "region": "pearl_river_delta",
        "pain_point": "消费电子薄型电芯的安装空间有限，硅碳负极循环后胀厚会挤占预留空间；需在保持容量的同时控制极片和电芯厚度变化。",
        "expected_solution": "希望研发方提供适用于薄型消费电芯的硅碳颗粒与粘结剂组合，在我方电芯试制条件下比较改进方案和现用品，交付极片、试制电芯与满电厚度记录；研发入口可为可重复的实验器件，后续再开展电芯适配。",
        "technical_metrics": [
            {
                "name": "满电极片厚度变化",
                "value": "固定面载量、SOC、循环程序及测量压力，候选样品厚度变化不得高于现用品对照；同时记录电芯厚度与容量，避免仅以极片结果代替电芯结果。",
                "unit": "μm",
            }
        ],
    },
    "dem_053": {
        "title": "快充石墨负极析锂边界验证",
        "application_scenarios": ["ev_power"],
        "pain_point": "动力电芯客户需要确定石墨负极在不同温度和充电倍率下的析锂边界，现有材料评估不足以支持快充工况选型。",
        "expected_solution": "联合研发方在固定电芯配方、面载量及测试程序下，对候选石墨和现用品进行倍率、温度交叉验证，并用拆解结果核验析锂，交付安全充电工况建议与材料筛选记录；本条不交付在线 BMS 预警算法。",
        "technical_metrics": [
            {
                "name": "未检出析锂的充电倍率边界",
                "value": "按温度分组报告；固定拆解判据与观察方法，候选样品的可接受倍率不得低于现用品，并附对应拆解证据。",
                "unit": "C",
            }
        ],
    },
    "dem_066": {
        "pain_point": "水系钠电封装电芯在待机静置时可能产气并引起内压变化，影响储能设备的长期待机可靠性；电解液储存稳定性与电芯静置产气需要分别测试。",
        "expected_solution": "由研发方筛选低析气配方，在同容量、同封装、同SOC的水系钠电试制电芯上进行静置对照，记录产气、内压与开路电压；配液储存另设试验，不以储罐压力代替电芯结果。",
        "technical_metrics": [
            {
                "name": "静置单位容量产气量",
                "value": "固定温度、静置时长、SOC和封装方式，候选配方单位容量产气量不得高于现配方；附气体计量方法及静置记录。",
                "unit": "mL/Ah",
            }
        ],
    },
    "dem_099": {
        "title": "工商业储能超级电容脉冲功率缓冲",
        "pain_point": "工商业储能系统遇到短时回馈功率或负载突变时，直流侧电压容易波动，需要超级电容模组吸收脉冲能量并稳定输出。",
        "expected_solution": "在我方工业超级电容模组与控制器基础上，优化电压限制和分组容量配置，在约定的脉冲回馈及负载突变工况下测试，交付模组样件、端压曲线与缓冲能量记录；本条应用于工商业储能，不再表述为车辆制动回收。",
        "technical_metrics": [
            {
                "name": "单次缓冲能量",
                "value": "在固定脉冲持续时间、初始电压和模组配置下报告，候选方案吸收或释放能量不得低于现用模组对照。",
                "unit": "kJ",
            },
            {
                "name": "脉冲期间最高端压",
                "value": "在相同脉冲工况下不得超过试验前确认的模组及直流接口额定限值，提交端压曲线。",
                "unit": "V",
            },
        ],
    },
}


def _fix_dates(row: dict, fields: tuple[str, ...]) -> bool:
    changed = False
    for field in fields:
        value = row.get(field)
        if isinstance(value, str) and DATE_ONLY.fullmatch(value):
            row[field] = value + "T00:00:00Z"
            changed = True
    return changed


def _invalid_metrics(extraction: dict) -> bool:
    for metric in extraction.get("key_metrics") or []:
        if not isinstance(metric, dict):
            return True
        for key in ("name", "value", "unit", "evidence"):
            value = metric.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return True
    return False


def _profile_map(profiles: list[dict]) -> dict[str, int]:
    return {p.get("achievement_id"): len(p.get("text", "")) for p in profiles if p.get("achievement_id")}


def build_labels(labels: list[dict], profiles: list[dict], version: str) -> Counter:
    lengths = _profile_map(profiles)
    w440 = next((r for r in labels if r.get("achievement_id") == "ach_openalex_W4401101842"), None)
    if w440 is None:
        raise SystemExit("W4401101842 not found")
    tags = w440.setdefault("tags", [])
    if not any(t.get("dimension") == "tech_field" and t.get("code") == "electrolyte" for t in tags):
        tags.append(
            {
                "tag_id": "tag_ach_openalex_W4401101842_tech_field_electrolyte",
                "achievement_id": "ach_openalex_W4401101842",
                "dimension": "tech_field",
                "code": "electrolyte",
                "is_primary": True,
                "confidence": 0.9,
                "evidence": "Research progress in lithium-ion solid electrolytes of oxidates; solid-state lithium-ion batteries replace liquid electrolytes with solid electrolytes.",
                "method": "human",
                "model": "s08-human",
                "prompt_version": "v0.1.1",
                "review_status": "approved",
                "created_at": CORRECTION_TIME,
            }
        )

    counts = Counter()
    for row in labels:
        row["dataset_version"] = version
        extraction = row.get("extraction") or {}
        row["extraction"] = extraction
        aid = row.get("achievement_id", "")
        tags = row.get("tags") or []
        tech = [t for t in tags if t.get("dimension") == "tech_field"]
        has_primary = any(t.get("is_primary") for t in tech)
        reasons = []
        if extraction.get("trl") is None:
            reasons.append("trl=null")
        if not has_primary:
            reasons.append("no_primary_tech_field")
        if _invalid_metrics(extraction):
            reasons.append("key_metrics")
        if any(not (t.get("evidence") or "").strip() for t in tags):
            reasons.append("missing_evidence")
        plen = lengths.get(aid, 0)
        if plen == 0 or plen < 150:
            reasons.append("profile_missing_or_short")

        current = row.get("review_status")
        # A row that was only flagged for >250-char profile is accepted under
        # the PM's business rule. Preserve unexplained flags (LLM/retry), and
        # clear the W440 false flag after its missing primary is fixed.
        if current == "needs_review" and not reasons:
            if aid == "ach_openalex_W4401101842":
                pass
            elif plen > 250:
                pass
            else:
                reasons.append("llm_or_retry_flag")

        status = "needs_review" if reasons else "pending"
        row["review_status"] = status
        if extraction:
            extraction["review_status"] = status
            extraction["extraction_run_id"] = f"{version}-20261123"
        counts[status] += 1
        counts["reasons:" + ",".join(reasons)] += 1
        for tag in tags:
            # Keep tag-level status conservative; W440's human-approved tag is
            # the only non-pending tag in this correction pass.
            if tag.get("tag_id") != "tag_ach_openalex_W4401101842_tech_field_electrolyte":
                if tag.get("review_status") not in ("approved", "rejected"):
                    tag["review_status"] = "pending"
    return counts


def build_demands(demands: list[dict], version: str) -> Counter:
    counts = Counter()
    for row in demands:
        did = row.get("demand_id")
        row["dataset_version"] = version
        _fix_dates(row, ("created_at", "updated_at"))
        if did in S07_PATCHES:
            patch = S07_PATCHES[did]
            for key, value in patch.items():
                row[key] = deepcopy(value)
            row["updated_at"] = CORRECTION_TIME
            row["content_hash"] = content_hash(row)
            counts["patched"] += 1
        # Ensure all demand hashes still follow the documented concatenation.
        if row.get("content_hash") != content_hash(row):
            row["content_hash"] = content_hash(row)
            counts["hash_recomputed"] += 1
    return counts


def build_enterprises(enterprises: list[dict]) -> Counter:
    counts = Counter()
    for row in enterprises:
        if _fix_dates(row, ("created_at",)):
            counts["datetime_fixed"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build v0.1.1 data-delivery files")
    parser.add_argument("--source-version", default="v0.1")
    parser.add_argument("--target-version", default="v0.1.1")
    args = parser.parse_args()
    src, dst = args.source_version, args.target_version

    labels = read_jsonl(PROCESSED / f"achievements_labeled_{src}.jsonl")
    profiles = read_jsonl(PROCESSED / f"capability_profiles_{src}.jsonl")
    achievements = read_jsonl(PROCESSED / f"achievements_clean_{src}.jsonl")
    demands = read_jsonl(PROCESSED / f"demands_{src}.jsonl")
    enterprises = read_jsonl(PROCESSED / f"enterprises_{src}.jsonl")

    label_counts = build_labels(labels, profiles, dst)
    demand_counts = build_demands(demands, dst)
    ent_counts = build_enterprises(enterprises)
    for row in achievements:
        row["dataset_version"] = dst
    for row in profiles:
        row["dataset_version"] = dst

    # Eval annotations are frozen; only the version metadata changes.
    q_path = EVAL / f"retrieval_queries_{src}.jsonl"
    p_path = EVAL / f"pair_labels_{src}.jsonl"
    queries = read_jsonl(q_path)
    pairs = read_jsonl(p_path)
    for row in queries + pairs:
        row["dataset_version"] = dst

    outputs = {
        "achievements_clean": PROCESSED / f"achievements_clean_{dst}.jsonl",
        "demands": PROCESSED / f"demands_{dst}.jsonl",
        "enterprises": PROCESSED / f"enterprises_{dst}.jsonl",
        "labeled": PROCESSED / f"achievements_labeled_{dst}.jsonl",
        "profiles": PROCESSED / f"capability_profiles_{dst}.jsonl",
        "queries": EVAL / f"retrieval_queries_{dst}.jsonl",
        "pairs": EVAL / f"pair_labels_{dst}.jsonl",
    }
    write_jsonl(outputs["achievements_clean"], achievements)
    write_jsonl(outputs["demands"], demands)
    write_jsonl(outputs["enterprises"], enterprises)
    write_jsonl(outputs["labeled"], labels)
    write_jsonl(outputs["profiles"], profiles)
    write_jsonl(outputs["queries"], queries)
    write_jsonl(outputs["pairs"], pairs)
    shutil.copy2(EVAL / f"retrieval_queries_{src}.csv", EVAL / f"retrieval_queries_{dst}.csv")
    shutil.copy2(EVAL / f"pair_labels_{src}.csv", EVAL / f"pair_labels_{dst}.csv")

    tag_count = sum(len(r.get("tags") or []) for r in labels)
    primary_count = sum(
        1 for r in labels
        if any(t.get("is_primary") for t in (r.get("tags") or []) if t.get("dimension") == "tech_field")
    )
    trl_null = sum(1 for r in labels if (r.get("extraction") or {}).get("trl") is None)
    needs = sum(1 for r in labels if r.get("review_status") == "needs_review")
    manifest = {
        "sprint": "2026-11-22",
        "task": "S-08",
        "dataset_version": dst,
        "taxonomy_version": "v0.1",
        "embedding_model_version": "qwen3.7-text-embedding-flash-1024-v1",
        "base_dataset_version": src,
        "base_commit": "bcb6025",
        "run_id": f"{dst}-20261123",
        "source": "v0.1 accepted S-05 snapshot + S-07 review patches",
        "corrections": [
            "S-07 seven P1 demand patches",
            "50 date-only datetimes normalized to 00:00:00Z",
            "W4401101842 electrolyte primary tag added",
            "TRL=null normalized to needs_review",
            "profile length >250 accepted; no length-only needs_review",
            "version fields bumped to v0.1.1",
        ],
        "files": {
            key: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(path)}
            for key, path in outputs.items()
        },
        "quality": {
            "achievements": len(achievements),
            "demands": len(demands),
            "enterprises": len(enterprises),
            "achievement_tags": tag_count,
            "achievement_primary_tech_field": primary_count,
            "needs_review": needs,
            "trl_null": trl_null,
            "queries": len(queries),
            "pairs": len(pairs),
            "demand_patches": demand_counts["patched"],
            "demand_hashes_recomputed": demand_counts["hash_recomputed"],
            "enterprise_datetimes_fixed": ent_counts["datetime_fixed"],
            "profile_policy": "150-250 recommended; >250 accepted",
        },
        "evaluation": {"retrieval_queries": len(queries), "pairs": len(pairs), "annotation_status": "frozen"},
    }
    (MANIFEST / f"dataset_{dst}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest["quality"], ensure_ascii=False, indent=2))
    print(json.dumps(label_counts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
