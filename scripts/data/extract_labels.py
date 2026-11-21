#!/usr/bin/env python3
"""LLM 抽取成果标签 / TRL / 关键指标，并生成中文能力画像。

严格依据：
  - data/spec/taxonomy_v0.1.md  §8（LLM 映射规则与硬约束）、§2/§3/§4（枚举与 TRL 口径）
  - data/spec/data_contract_v0.1.md  §4.3（achievement_text）/ §4.4（achievement_tag）/ §4.5（achievement_extraction）
  - scripts/common/llm_client.py（统一走共享客户端，不自己写 HTTP）

输入：
  data/processed/achievements_clean_<version>.jsonl   （完整清洗集，本地/交接包，不入库）

输出：
  data/processed/achievements_labeled_<version>.jsonl  （每条成果：tags + extraction）
  data/processed/capability_profiles_<version>.jsonl   （每条成果：capability_profile_zh）
  data/manifests/extract_<run-id>.json                 （运行清单）
  data/interim/api_usage.jsonl                         （由 llm_client 自动记录）

硬约束（见 taxonomy §8.3，脚本内强制校验，不依赖模型自觉）：
  1. 只能输出 taxonomy 中的枚举 code；非法 code 直接拒绝并重试，重试耗尽后剔除非法项。
  2. 每个标签必须有 evidence；无证据时 confidence ≤0.4。
  3. tech_field 恰好 1 个 is_primary=true，最多 2 个。
  4. trl 必须带 trl_evidence；无证据 / 非法值 / 论文越级（5—6 无中试放大、7—9 无装车量产证据）均 trl=null 并标 needs_review。
  5. 不确定字段写 unknown，禁止编造 IP/合作模式/性能指标。
  6. 成果侧 cooperation_mode 只是潜在模式，confidence ≤0.5，不参与硬过滤。

review_status 口径（对齐契约）：
  - achievement_tag 只允许 pending/approved/rejected，故标签一律写 "pending"；缺证据/低置信只体现在
    evidence 为空 + confidence≤0.4，并上提到记录级。
  - needs_review 只写进顶级记录（labeled_record["review_status"]）与 extraction["review_status"]，
    成果本身**不丢弃**、不下线。
  - 画像缺失 → capability_profile_zh=null，前端回退 abstract_preview；不阻断该成果的标签/向量链路。
  - review_reasons 分类：missing_evidence / trl / profile / key_metrics / tech_field / retry_exhausted。

ID 归属：tag_id / extraction_id / text_id 不由本脚本生成（由 load_db.py 导入器生成），
  JSONL 中不包含这些 ID 字段；标签以 achievement_id + dimension + code 交叉引用。

用法：
  # 环境自检（不调用 API）
  python scripts/common/llm_client.py --check

  # 薄切片 30 条校准试跑（先跑通）
  python scripts/data/extract_labels.py --version v0.1-thin --limit 30

  # 断点续跑（跳过已处理的成果）
  python scripts/data/extract_labels.py --version v0.1-thin --resume

  # 全量（数据扩到 300—400 后切 version 为 v0.1）
  python scripts/data/extract_labels.py --version v0.1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# 让脚本在 `python scripts/data/extract_labels.py` 与 `cd scripts/data` 两种方式下都能导入。
_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import (  # noqa: E402
    APPLICATION_SCENARIOS,
    COOPERATION_MODES,
    IP_STATUSES,
    MANIFEST_DIR,
    PROCESSED_DIR,
    TECH_FIELDS,
)
from scripts.common.llm_client import DashScopeClient, LlmClientError, text_hash  # noqa: E402

PROMPT_VERSION = "v0.1"
TAXONOMY_VERSION = "v0.1"
MAX_ABSTRACT_CHARS = 4000  # 控制单条输入长度，避免超长摘要撑爆 token
DEFAULT_MAX_TOKENS = 2048   # 抽取 JSON + 150—250 字中文画像，1024 可能不够
SPRINT = "2026-11-22"       # 第一次冲刺

# 能力画像目标长度（契约 §4.3：150—250 字）
PROFILE_MIN_CHARS = 150
PROFILE_MAX_CHARS = 250

# needs_review 原因分类（manifest 与抽检报告据此归类，不报单一总数）
REVIEW_REASONS = (
    "missing_evidence",   # 标签缺 evidence（confidence 封顶 0.4）
    "trl",                # TRL 无证据 / 非法值 / 论文越级被降为 null
    "profile",            # 能力画像缺失或长度超界
    "key_metrics",        # 非法 key_metrics 项被丢弃
    "tech_field",         # 无合法 tech_field（标签覆盖不足）
    "retry_exhausted",    # 非法 code 重试耗尽，已剔除非法项
)

# ---------------------------------------------------------------------------
# 枚举中文标签与定义（与 taxonomy_v0.1.md 保持一致；仅用于构造 Prompt 与提示，
# 合法 code 的最终校验以 config.py 的集合为准）。
# ---------------------------------------------------------------------------
TECH_FIELD_LABELS = {
    "cathode_material": "正极材料（正极活性材料及改性/合成/包覆/掺杂，如 NCM/NCA、LFP/LMFP、富锂锰基、钠电正极、钴酸锂）",
    "anode_material": "负极材料（负极活性材料及改性/合成，如石墨、硅碳/硅氧、硬碳、锂金属、钛酸锂）",
    "electrolyte": "电解质（液态/固态/凝胶电解质、添加剂、离子导体，如硫化物、氧化物、聚合物、卤化物、复合）",
    "separator": "隔膜（隔离正负极的多孔膜及涂覆，如 PE/PP、陶瓷涂覆、PVDF/PMMA 涂覆）",
    "cell_system": "电芯与系统（电芯设计/制造工艺/模组/PACK/热管理/BMS/安全）",
    "recycling": "回收与梯次利用（退役电池回收、材料再生、梯次利用）",
    "flow_battery": "液流电池（材料/电堆/系统，如全钒、铁铬、锌基、有机液流）",
    "supercapacitor": "超级电容器（双电层/赝电容材料与器件，如活性炭、石墨烯、MXene）",
}

APPLICATION_SCENARIO_LABELS = {
    "ev_power": "动力电池（电动汽车、商用车、船舶/航空动力）",
    "grid_storage": "电网储能（发电侧/电网侧、调峰调频）",
    "cni_storage": "工商业储能（园区、数据中心、峰谷套利）",
    "residential_storage": "户用储能（家庭光储、便携储能）",
    "consumer_electronics": "消费电子（手机、笔电、穿戴、无人机）",
    "e_tool_two_wheeler": "电动工具/两轮车",
    "special": "特种应用（航空航天、军工、极寒/深海等）",
    "recycling_industry": "回收产业（退役电池回收、再生材料、梯次利用）",
}

COOPERATION_MODE_LABELS = {
    "transfer": "技术转让",
    "license": "技术许可",
    "joint_rd": "联合研发",
    "joint_lab": "共建实验室",
    "tech_service": "技术服务/咨询",
}

IP_STATUS_LABELS = {
    "granted": "已授权",
    "pending": "申请中",
    "published": "已公开",
    "unknown": "未知/不适用（论文默认 unknown）",
}

TRL_LEVELS = {
    1: "基本原理（计算/机理/假设，如 first-principles、DFT）",
    2: "技术概念（概念设计/提出机制）",
    3: "实验室验证（合成、纽扣电池 coin cell、小样）",
    4: "实验室器件（小软包 pouch cell、可重复原型）",
    5: "相关环境验证/中试（pilot-scale、scale-up、Ah 级）",
    6: "原型演示（module、pack-level、demonstrator）",
    7: "实际环境演示（field test、装车、real-world）",
    8: "系统定型（certified、production-ready、认证/定型）",
    9: "商业运行（commercial、mass production、量产/商用）",
}

# 启动时自检：Prompt 枚举与 config 合法集合必须一致，防止两处漂移。
assert set(TECH_FIELD_LABELS) == TECH_FIELDS, "TECH_FIELD_LABELS 与 config.TECH_FIELDS 不一致"
assert set(APPLICATION_SCENARIO_LABELS) == APPLICATION_SCENARIOS, "应用场景枚举漂移"
assert set(COOPERATION_MODE_LABELS) == COOPERATION_MODES, "合作模式枚举漂移"
assert set(IP_STATUS_LABELS) == IP_STATUSES, "IP 状态枚举漂移"


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Prompt 构造
# ---------------------------------------------------------------------------
def _enum_table(mapping: dict[str, str]) -> str:
    return "\n".join(f"- `{code}`：{label}" for code, label in mapping.items())


def _trl_table() -> str:
    return "\n".join(f"- {lvl}：{desc}" for lvl, desc in TRL_LEVELS.items())


def build_system_prompt() -> str:
    return f"""你是新能源电池领域的技术成果分析助手。给定一篇论文/专利的元数据（标题、摘要、期刊/年份、源关键词、源主题），你需要：

1. 将成果映射到给定的**枚举标签**（只能使用枚举中的 code，不得自创）；
2. 判断技术成熟度 TRL（1—9）；
3. 抽取材料体系、关键性能指标、工艺路线；
4. 生成一段面向产业语言的中文能力画像（150—250 字）。

## 枚举定义

【技术领域 tech_field】（每个成果 1—2 个，恰好 1 个 is_primary=true，按“核心创新点”定主标签）
{_enum_table(TECH_FIELD_LABELS)}

【应用场景 application_scenario】（最多 3 个）
{_enum_table(APPLICATION_SCENARIO_LABELS)}

【合作模式 cooperation_mode】（成果侧仅作“潜在模式”推断，confidence ≤0.5）
{_enum_table(COOPERATION_MODE_LABELS)}

【知识产权状态 ip_status】（论文默认 unknown）
{_enum_table(IP_STATUS_LABELS)}

【TRL 判定口径】
{_trl_table()}

## 硬规则（必须遵守）

1. 只能输出上述枚举 code；非法 code 会被拒绝并要求重试。
2. 每个标签必须给出 `evidence`（原文摘录片段）；无证据时 `confidence` 必须 ≤0.4。
3. `tech_fields` 恰好 1 个 `is_primary=true`，最多 2 个。
4. `trl` 必须给出 `trl_evidence`；无证据则输出 null。
5. 论文默认 TRL 最多到 4；无中试/放大证据不得标 5，无装车/现场/量产证据不得标 7—9。
6. 不确定的字段写 `unknown`，禁止编造 IP 状态、合作模式、性能指标。
7. `capability_profile_zh` 不是逐字翻译，而是面向产业语言的技术能力摘要（150—250 字），保留关键性能指标与适用场景；机器生成、原文为准。

## 输出 JSON schema（只输出 JSON，不要 markdown 代码块）

{{
  "tech_fields": [{{"code": "electrolyte", "is_primary": true, "confidence": 0.93, "evidence": "原文摘录"}}],
  "application_scenarios": [{{"code": "ev_power", "confidence": 0.72, "evidence": "原文摘录"}}],
  "trl": 4,
  "trl_confidence": 0.66,
  "trl_evidence": "原文摘录",
  "material_system": "中文材料体系，如 硫化物固态电解质",
  "key_metrics": [{{"name": "ionic conductivity", "value": "10", "unit": "mS/cm", "evidence": "原文摘录"}}],
  "process": ["ball milling", "cold sintering"],
  "cooperation_modes": [{{"code": "joint_rd", "confidence": 0.4, "evidence": "潜在依据"}}],
  "ip_status": "unknown",
  "capability_profile_zh": "150—250 字中文能力画像"
}}"""


def build_user_message(ach: dict) -> str:
    abstract = (ach.get("abstract_original") or ach.get("abstract_truncated") or "").strip()
    if len(abstract) > MAX_ABSTRACT_CHARS:
        abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
    keywords = ", ".join(ach.get("keywords") or []) or "（无）"
    topics = ", ".join(ach.get("topics") or []) or "（无）"
    return (
        "请分析以下成果并输出 JSON。\n\n"
        f"成果 ID：{ach.get('achievement_id')}\n"
        f"类型：{ach.get('type')}\n"
        f"标题：{ach.get('title_original')}\n"
        f"摘要：{abstract or '（缺失）'}\n"
        f"期刊/会议：{ach.get('venue') or '（未知）'}\n"
        f"年份：{ach.get('publication_year')}\n"
        f"源关键词：{keywords}\n"
        f"源主题：{topics}"
    )


# ---------------------------------------------------------------------------
# 校验与归一化（硬约束落地在代码里）
# ---------------------------------------------------------------------------
def _clean_coded_list(
    raw: object,
    allowed: set[str],
) -> tuple[list[dict], list[str]]:
    """清洗一个 code 列表，返回 (合法项, 非法 code 描述)。"""
    if not isinstance(raw, list):
        return [], ["字段不是列表"]
    valid: list[dict] = []
    illegal: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            illegal.append(repr(item))
            continue
        code = item.get("code")
        if not isinstance(code, str) or code not in allowed:
            illegal.append(repr(code))
            continue
        if code in seen:  # 同维度去重，保首个
            continue
        seen.add(code)
        valid.append(item)
    return valid, illegal


def _apply_evidence_rule(item: dict) -> bool:
    """返回是否需要 needs_review；就地修正 confidence。"""
    evidence = (item.get("evidence") or "").strip()
    if not evidence:
        item["confidence"] = min(_clamp01(item.get("confidence")), 0.4)
        return True
    item["confidence"] = _clamp01(item.get("confidence"))
    return False


def _normalize_trl(
    raw: dict, source_type: str | None
) -> tuple[int | None, str | None, bool, str | None]:
    """返回 (trl, trl_evidence, needs_review, reason)。

    严格降级（taxonomy §4 TRL 硬规则）：
    - 未断言 trl → (None, None, False, None)
    - 非法值 / 无证据 / 论文越级 → trl=null + needs_review，reason="trl"
    - 论文/预印本 TRL 5—6 需中试/放大/原型证据，7—9 需装车/量产/认证/定型证据
    """
    trl = raw.get("trl")
    evidence = (raw.get("trl_evidence") or "").strip()
    if trl is None:
        return None, None, False, None
    if not isinstance(trl, int) or isinstance(trl, bool) or not 1 <= trl <= 9:
        return None, None, True, "trl"  # 非法值 → null + needs_review
    if not evidence:
        return None, None, True, "trl"  # 无证据 → null + needs_review
    if source_type in ("article", "review", "preprint"):
        ev_low = evidence.lower()
        if trl >= 7:
            # 只接受明确现场/装车/量产证据，去掉过宽的 vehicle/commercial。
            strong = ("field test", "vehicle demo", "mass production",
                      "装车", "量产", "认证", "定型")
            if not any(k in ev_low for k in strong):
                return None, None, True, "trl"
        elif trl >= 5:
            pilot = ("pilot", "scale-up", "scale up", "ah-level",
                     "中试", "放大", "prototype", "demonstrator", "module", "pack-level")
            if not any(k in ev_low for k in pilot):
                return None, None, True, "trl"  # 5—6 无中试/原型证据 → null，不保留只标 review
    return trl, evidence, False, None


def _clean_key_metrics(raw: object) -> tuple[list[dict], bool]:
    """只接受 {name,value,unit,evidence} 且 name/value 非空；非法项丢弃。

    返回 (合法指标列表, 是否有非法项被丢弃)。全部为空不阻断，详情页不渲染指标区。
    """
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True
    cleaned: list[dict] = []
    dropped = False
    for m in raw:
        if not isinstance(m, dict):
            dropped = True
            continue
        name = str(m.get("name") or "").strip()
        value = str(m.get("value") or "").strip()
        if not name or not value:
            dropped = True
            continue
        cleaned.append(
            {
                "name": name,
                "value": value,
                "unit": str(m.get("unit") or "").strip(),
                "evidence": str(m.get("evidence") or "").strip(),
            }
        )
    return cleaned, dropped


def validate_extraction(
    raw: object,
    source_type: str | None,
) -> tuple[dict, list[str], bool, list[str]]:
    """校验并归一化模型输出。

    返回 (normalized, illegal_errors, needs_review, review_reasons)。
    - illegal_errors：非空表示存在非法枚举 code（调用方据此重试）。
    - needs_review：存在缺证据 / TRL 降级 / 画像缺失或超界 / key_metrics 非法等问题。
    - review_reasons：needs_review 的原因分类，取值见 REVIEW_REASONS。
    """
    if not isinstance(raw, dict):
        return {}, ["模型输出不是 JSON 对象"], True, ["invalid_output"]

    illegal: list[str] = []
    needs_review = False
    reasons: list[str] = []

    def _flag(reason: str) -> None:
        nonlocal needs_review
        needs_review = True
        if reason not in reasons:
            reasons.append(reason)

    # tech_fields：恰好 1 个 primary，最多 2 个
    tech_items, tech_illegal = _clean_coded_list(raw.get("tech_fields"), TECH_FIELDS)
    illegal += tech_illegal
    if not tech_items:
        _flag("tech_field")
    else:
        # 去重后最多 2 个
        if len(tech_items) > 2:
            tech_items = tech_items[:2]
        # 归一化 primary：取 confidence 最高者为 primary，其余 false
        best_idx = max(range(len(tech_items)), key=lambda i: _clamp01(tech_items[i].get("confidence")))
        for i, item in enumerate(tech_items):
            item["is_primary"] = (i == best_idx)
            if _apply_evidence_rule(item):
                _flag("missing_evidence")

    # application_scenarios：最多 3 个
    app_items, app_illegal = _clean_coded_list(raw.get("application_scenarios"), APPLICATION_SCENARIOS)
    illegal += app_illegal
    app_items = app_items[:3]
    for item in app_items:
        if _apply_evidence_rule(item):
            _flag("missing_evidence")

    # cooperation_modes：confidence ≤0.5，缺证据 ≤0.4
    coop_items, coop_illegal = _clean_coded_list(raw.get("cooperation_modes"), COOPERATION_MODES)
    illegal += coop_illegal
    for item in coop_items:
        item["confidence"] = min(_clamp01(item.get("confidence")), 0.5)
        if _apply_evidence_rule(item):
            _flag("missing_evidence")

    # ip_status
    ip_status = raw.get("ip_status")
    if ip_status not in IP_STATUSES:
        if isinstance(ip_status, str) and ip_status != "":
            illegal.append(f"ip_status={ip_status!r}")
        ip_status = "unknown"

    # trl（严格降级）
    trl, trl_evidence, trl_review, trl_reason = _normalize_trl(raw, source_type)
    if trl_review:
        _flag(trl_reason or "trl")

    # key_metrics：非法项丢弃并标 review
    key_metrics, km_dropped = _clean_key_metrics(raw.get("key_metrics"))
    if km_dropped:
        _flag("key_metrics")

    # capability_profile_zh：目标 150—250 字；缺失 → null，超界 → 保留但标 review
    profile_text = (raw.get("capability_profile_zh") or "").strip()
    if not profile_text:
        profile_text = None
        _flag("profile")
    elif len(profile_text) < PROFILE_MIN_CHARS or len(profile_text) > PROFILE_MAX_CHARS:
        _flag("profile")

    normalized = {
        "tech_fields": tech_items,
        "application_scenarios": app_items,
        "cooperation_modes": coop_items,
        "ip_status": ip_status,
        "trl": trl,
        "trl_confidence": _clamp01(raw.get("trl_confidence")) if trl is not None else None,
        "trl_evidence": trl_evidence,
        "material_system": (raw.get("material_system") or "unknown").strip() or "unknown",
        "key_metrics": key_metrics,
        "process": raw.get("process") if isinstance(raw.get("process"), list) else [],
        "capability_profile_zh": profile_text,
        "_needs_review": needs_review,
        "_review_reasons": sorted(set(reasons)),
    }

    return normalized, illegal, needs_review, sorted(set(reasons))


# ---------------------------------------------------------------------------
# 记录构造（与 data_contract_v0.1.md 字段对齐）
# ---------------------------------------------------------------------------
def build_records(
    ach: dict,
    normalized: dict,
    raw_output: dict,
    *,
    model: str,
    dataset_version: str,
    run_id: str,
) -> tuple[dict, dict | None, bool]:
    """返回 (labeled_record, profile_record_or_None, needs_review)。

    review_status 口径：tag 一律 "pending"（achievement_tag 仅允许 pending/approved/rejected）；
    needs_review 只写进 extraction 与顶级记录，单一来源 normalized["_needs_review"]，避免与 stats 不一致。
    tag_id / extraction_id / text_id 由导入器生成，不在此处写入 JSONL。
    """
    achievement_id = ach["achievement_id"]
    created_at = _now_utc()
    needs_review = bool(normalized.get("_needs_review", False))

    def _tag(dimension: str, code: str, item: dict, is_primary: bool) -> dict:
        # achievement_tag 只允许 pending/approved/rejected；needs_review 只上提到记录级。
        # tag_id 由导入器生成，不在此处填写。
        return {
            "achievement_id": achievement_id,
            "dimension": dimension,
            "code": code,
            "is_primary": is_primary,
            "confidence": _clamp01(item.get("confidence")),
            "evidence": (item.get("evidence") or "").strip(),
            "method": "llm",
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "review_status": "pending",
            "created_at": created_at,
        }

    tags: list[dict] = []
    for item in normalized["tech_fields"]:
        tags.append(_tag("tech_field", item["code"], item, bool(item.get("is_primary"))))
    for item in normalized["application_scenarios"]:
        tags.append(_tag("application_scenario", item["code"], item, False))
    for item in normalized["cooperation_modes"]:
        tags.append(_tag("cooperation_mode", item["code"], item, False))

    record_review = "needs_review" if needs_review else "pending"

    extraction = {
        "achievement_id": achievement_id,
        "material_system": normalized["material_system"],
        "key_metrics": normalized["key_metrics"],
        "process": normalized["process"],
        "trl": normalized["trl"],
        "trl_confidence": normalized["trl_confidence"],
        "trl_evidence": normalized["trl_evidence"],
        "ip_status": normalized["ip_status"],
        "extraction_run_id": run_id,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "raw_output": raw_output,
        "review_status": record_review,
        "created_at": created_at,
    }

    labeled_record = {
        "achievement_id": achievement_id,
        "dataset_version": dataset_version,
        "taxonomy_version": TAXONOMY_VERSION,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "extraction_run_id": run_id,
        "review_status": record_review,
        "tags": tags,
        "extraction": extraction,
    }

    profile_text = normalized["capability_profile_zh"]
    profile_record = None
    if profile_text:  # 缺失时 capability_profile_zh=null，不生成画像记录，成果仍保留
        profile_record = {
            "achievement_id": achievement_id,
            "text_type": "capability_profile_zh",
            "language": "zh",
            "text": profile_text,
            "method": "llm",
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "text_hash": text_hash(profile_text),
            "dataset_version": dataset_version,
            "created_at": created_at,
        }
    return labeled_record, profile_record, needs_review


# ---------------------------------------------------------------------------
# 抽取（含非法 code 重试）
# ---------------------------------------------------------------------------
def extract_one(
    client: DashScopeClient,
    ach: dict,
    *,
    model: str | None,
    max_field_retries: int,
) -> tuple[dict, dict, bool, int, list[str]]:
    """返回 (normalized, raw_output, needs_review, retries_used, review_reasons)。"""
    system = build_system_prompt()
    user = build_user_message(ach)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    source_type = ach.get("type")
    last_raw: dict = {}
    for attempt in range(max_field_retries + 1):
        raw = client.chat_json(messages, model=model, max_tokens=DEFAULT_MAX_TOKENS)
        last_raw = raw
        normalized, illegal, needs_review, reasons = validate_extraction(raw, source_type)
        if not illegal:
            return normalized, raw, needs_review, attempt, reasons
        feedback = (
            "上一轮输出存在非法枚举 code，已拒绝。请修正后重新只输出 JSON：\n"
            + "\n".join(f"- 非法：{e}" for e in illegal)
        )
        messages += [
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {"role": "user", "content": feedback},
        ]
    # 重试耗尽：剔除非法项，标记 needs_review。
    normalized, _, needs_review, reasons = validate_extraction(last_raw, source_type)
    normalized["_needs_review"] = True
    reasons = sorted(set(reasons) | {"retry_exhausted"})
    return normalized, last_raw, True, max_field_retries, reasons


# ---------------------------------------------------------------------------
# 断点续跑辅助
# ---------------------------------------------------------------------------
def _load_done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["achievement_id"])
            except (ValueError, KeyError):
                continue
    return done


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _relpath(path: Path) -> str:
    """转仓库相对路径；转不了就回退绝对路径。"""
    try:
        return str(path.resolve().relative_to(_ROOT.resolve()))
    except ValueError:
        return str(path)


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input) if args.input else PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    out_dir = Path(args.output_dir) if args.output_dir else PROCESSED_DIR
    labeled_path = out_dir / f"achievements_labeled_{args.version}.jsonl"
    profile_path = out_dir / f"capability_profiles_{args.version}.jsonl"

    if not input_path.exists():
        print(f"[错误] 未找到输入文件：{input_path}", file=sys.stderr)
        print("       请把交接包中的 achievements_clean_<version>.jsonl 放到 data/processed/，", file=sys.stderr)
        print("       或用 --input 指定路径。", file=sys.stderr)
        return 2

    # 幂等：非 --resume 时拒绝覆盖已有输出，保证连续两次运行不重复追加。
    if not args.resume and (labeled_path.exists() or profile_path.exists()):
        print("[错误] 输出文件已存在，拒绝覆盖以避免重复追加：", file=sys.stderr)
        if labeled_path.exists():
            print(f"  {labeled_path}", file=sys.stderr)
        if profile_path.exists():
            print(f"  {profile_path}", file=sys.stderr)
        print("       请删除后重跑，或加 --resume 断点续跑。", file=sys.stderr)
        return 2

    try:
        client = DashScopeClient()
    except LlmClientError as exc:
        print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
        print("       请先 `python scripts/common/llm_client.py --check` 核对 .env。", file=sys.stderr)
        return 2

    achievements: list[dict] = []
    with input_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    achievements.append(json.loads(line))
                except ValueError:
                    print(f"[警告] 跳过无法解析的行：{line[:80]}…", file=sys.stderr)

    done_ids = _load_done_ids(labeled_path) if args.resume else set()
    todo = [a for a in achievements if a.get("achievement_id") not in done_ids]
    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        print("没有待处理的成果（已全部处理，或 --limit 为 0）。")
        return 0

    run_id = args.run_id or f"{args.version}-{datetime.now(timezone.utc):%Y%m%d}"
    model = args.model or client.chat_model
    started = _now_utc()

    print(f"输入：{input_path}（共 {len(achievements)} 条）")
    print(f"待处理：{len(todo)} 条（续跑跳过 {len(achievements) - len(todo)} 条）")
    print(f"模型：{model}   prompt_version={PROMPT_VERSION}   run_id={run_id}")
    print(f"输出：{labeled_path}\n      {profile_path}\n")

    stats = {
        "ok": 0, "needs_review": 0, "failed": 0, "written": 0,
        "profiles_written": 0, "profile_missing": 0, "retries_used": 0,
    }
    reason_counter: Counter = Counter()
    for idx, ach in enumerate(todo, 1):
        aid = ach.get("achievement_id", "?")
        try:
            normalized, raw, needs_review, retries, reasons = extract_one(
                client, ach, model=model, max_field_retries=args.max_retries
            )
            stats["retries_used"] += retries
            labeled, profile, rec_review = build_records(
                ach, normalized, raw,
                model=model, dataset_version=args.version, run_id=run_id,
            )
            _append_jsonl(labeled_path, labeled)
            stats["written"] += 1
            if profile:
                _append_jsonl(profile_path, profile)
                stats["profiles_written"] += 1
            else:
                stats["profile_missing"] += 1
            if rec_review:
                stats["needs_review"] += 1
            else:
                stats["ok"] += 1
            for reason in reasons:
                reason_counter[reason] += 1
            print(f"[{idx}/{len(todo)}] {aid}  needs_review={rec_review}  retries={retries}  reasons={reasons}")
        except Exception as exc:  # noqa: BLE001 —— 单条失败不中断全量
            stats["failed"] += 1
            print(f"[{idx}/{len(todo)}] {aid}  失败：{exc}", file=sys.stderr)

    manifest = {
        "run_id": run_id,
        "stage": "extract",
        "sprint": SPRINT,
        "status": (
            "success"
            if stats["failed"] == 0
            else ("failed" if stats["failed"] == len(todo) else "partial")
        ),
        "dataset_version": args.version,
        "taxonomy_version": TAXONOMY_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "input_path": _relpath(input_path),
        "labeled_path": _relpath(labeled_path),
        "profile_path": _relpath(profile_path),
        "started_at": started,
        "finished_at": _now_utc(),
        "input_count": len(achievements),
        "processed_count": len(todo),
        "output_count": stats["written"],
        "ok": stats["ok"],
        "needs_review": stats["needs_review"],
        "failed": stats["failed"],
        "profiles_written": stats["profiles_written"],
        "profile_missing": stats["profile_missing"],
        "retries_used": stats["retries_used"],
        "review_reasons": dict(reason_counter),
        "config": {
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "max_retries": args.max_retries,
            "limit": args.limit,
            "resume": args.resume,
        },
        "git_commit": _git_commit(),
        "args": vars(args),
    }
    manifest_path = MANIFEST_DIR / f"extract_{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：ok={stats['ok']}  needs_review={stats['needs_review']}  failed={stats['failed']}")
    print(f"画像：written={stats['profiles_written']}  missing={stats['profile_missing']}")
    print(f"needs_review 分类：{dict(reason_counter)}")
    print(f"清单：{manifest_path}")
    return 0 if stats["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="LLM 抽取成果标签/TRL/指标 + 生成中文能力画像",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1-thin", help="数据版本，决定输入/输出文件名")
    parser.add_argument("--input", default=None, help="覆盖输入 jsonl 路径")
    parser.add_argument("--output-dir", default=None, help="覆盖输出目录（默认 data/processed/）")
    parser.add_argument("--run-id", default=None, help="运行 ID（默认 <version>-<日期>）")
    parser.add_argument("--model", default=None, help="覆盖对话模型（默认读 .env 的 QWEN_CHAT_MODEL）")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 条（用于 30 条校准试跑）")
    parser.add_argument("--resume", action="store_true", help="断点续跑：跳过已存在于输出文件的成果")
    parser.add_argument("--max-retries", type=int, default=2, help="非法 code 的最大重试次数")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
