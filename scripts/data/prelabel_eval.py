#!/usr/bin/env python3
"""用 LLM 预标检索 query 与 pair 评测集，产出人工复核工作表。

这不是“替代人工标注”，而是把从零阅读 450 条候选摘要的工作，变成
“确认/修正模型草稿”。正式标注仍由人复核并在 `human_grade` 列签字；
独立双标子集必须使用不带 LLM 分数的空白表另标。

输入（默认）：
  data/eval/retrieval_queries_<version>.jsonl
  data/eval/pair_labels_<version>.jsonl
  data/processed/achievements_clean_<version>.jsonl
  data/processed/demands_<version>.jsonl
  data/processed/achievements_labeled_<version>.jsonl   （可选，用于 TRL）

输出（默认 data/interim/eval_prelabel/<version>/）：
  query_prelabel.jsonl                 一条 query 一行，含候选级草稿
  query_candidates_review.csv          一条候选一行（20×20=400 行），人工改 human_grade
  query_candidates_review_high.csv     只含高优先级复核项
  pair_prelabel.jsonl                  一对 pair 一行
  pair_review.csv                      50 行，人工改 human_grade / human_note
  pair_review_high.csv                 只含高优先级复核项
  review_summary.md                    口径、优先级和复核说明
  data/manifests/prelabel_eval_<run-id>.json

用法：
  python scripts/data/prelabel_eval.py --version v0.1 --only queries
  python scripts/data/prelabel_eval.py --version v0.1 --only queries --limit-queries 1
  python scripts/data/prelabel_eval.py --version v0.1

  # 全量数据不在 data/processed 时显式指定
  python scripts/data/prelabel_eval.py --version v0.1 \
    --achievements "E:/SEM-软工管/_review/s02_huangxinyue_20261122/data/processed/achievements_clean_v0.1.jsonl" \
    --demands "E:/SEM-软工管/_review/s02_huangxinyue_20261122/data/processed/demands_v0.1.jsonl"
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import DATA_DIR, EVAL_DIR, MANIFEST_DIR, PROCESSED_DIR  # noqa: E402
from scripts.common.llm_client import (  # noqa: E402
    DashScopeClient,
    LlmClientError,
)

PROMPT_VERSION = "prelabel_v0.1"
SPRINT = "2026-11-22"
DEFAULT_VERSION = "v0.1"
MAX_ABSTRACT_CHARS = 1800
QUERY_MAX_TOKENS = 4096
PAIR_MAX_TOKENS = 1024
QUERY_PRE_REVIEW_PRIORITY = 0.75

RUBRIC = """\
评分口径（0/1/2，评判的是“技术适配度”，不是成交概率）：
- 2 分（强相关）：技术领域一致；应用场景一致或兼容；TRL 差距 ≤2；合作模式可兼容；关键指标不冲突。
- 1 分（部分相关）：技术领域一致，但场景/TRL/合作模式有一项明显不匹配；或技术领域相邻但可迁移。
- 0 分（不相关）：技术领域不同且不可迁移；或关键约束冲突。

判定注意：
1. “摘要没有报告某项指标”不等于“指标冲突”。只有摘要明确给出低于需求/相反结论，才算冲突。
2. 不要因为标题相似、作者/机构/期刊/引用数给分。
3. evidence 必须逐字摘自候选成果的标题或摘要（英文原文）；找不到证据就降低 confidence，不要编造。
4. 技术领域按数据契约的 8 个枚举判断；跨领域但可迁移给 1 分，不可迁移给 0 分。
5. 需求/query 的指标是目标值；候选成果未覆盖某项指标本身不构成 0 分理由。
"""

QUERY_SCHEMA = """\
只输出 JSON 对象，不要 markdown 代码块：
{"grades": [{"achievement_id": "ach_...", "grade": 0, "confidence": 0.0, "evidence": "原文摘录", "rationale": "一句中文理由"}]}
必须覆盖全部候选，每个候选恰好一条；grade 只能是 0/1/2。"""

PAIR_SCHEMA = """\
只输出 JSON 对象，不要 markdown 代码块：
{"grade": 0, "confidence": 0.0, "evidence": "原文摘录", "rationale": "一句中文理由"}
grade 只能是 0/1/2；evidence 必须来自成果标题或摘要。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT.resolve()))
    except ValueError:
        return str(path)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _call_chat_json(
    client: DashScopeClient,
    messages: list[dict],
    *,
    model: str | None,
    max_tokens: int,
    timeout: float,
) -> object:
    """给 chat_json 套一个硬超时，避免本地代理挂住整批任务。

    urllib 的 socket 超时对“连接已建立但服务端不返数据”并不总是生效；
    这里用 daemon 线程，超时后主流程继续，未完成的调用不会阻塞退出。
    """
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["value"] = client.chat_json(
                messages, model=model, max_tokens=max_tokens, timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001 —— 交给主线程判断
            result["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise TimeoutError(f"LLM 调用超过 {timeout:.0f}s 未返回")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")


def _clamp_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _as_grade(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in (0, 1, 2):
        return value
    if isinstance(value, str) and value.strip() in ("0", "1", "2"):
        return int(value.strip())
    return None


def _norm_text(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    for dash in ("‐", "‑", "–", "—", "−"):
        value = value.replace(dash, "-")
    return re.sub(r"\s+", " ", value).strip()


def evidence_grounded(evidence: str, title: str, abstract: str) -> bool:
    """evidence 是否逐字出现在标题/摘要中（忽略空白和连字符差异）。"""
    quote = _norm_text(evidence)
    if len(quote) < 8:
        return False
    return quote in _norm_text(f"{title} {abstract}")


def review_priority(
    grade: int,
    confidence: float,
    evidence: str,
    grounded: bool,
    *,
    grade_threshold: float = QUERY_PRE_REVIEW_PRIORITY,
) -> str:
    """高优先级 = 影响指标的 1/2 分，或低置信/证据对不上/无证据的 0 分。"""
    if grade >= 1:
        return "high"
    if confidence < grade_threshold or not evidence or not grounded:
        return "high"
    return "normal"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _candidate_block(ach: dict, index: int, max_abstract_chars: int) -> str:
    abstract = (ach.get("abstract_original") or "").strip()
    if len(abstract) > max_abstract_chars:
        abstract = abstract[:max_abstract_chars] + "…"
    keywords = ", ".join(ach.get("keywords") or []) or "（无）"
    return (
        f"### {index}. {ach.get('achievement_id')}\n"
        f"标题：{ach.get('title_original') or '（无）'}\n"
        f"类型：{ach.get('type') or 'unknown'}；年份：{ach.get('publication_year') or 'unknown'}\n"
        f"关键词：{keywords}\n"
        f"摘要：{abstract or '（缺失）'}\n"
    )


def build_query_messages(
    query: dict,
    candidates: list[dict],
    *,
    max_abstract_chars: int = MAX_ABSTRACT_CHARS,
) -> list[dict]:
    system = (
        "你是新能源电池领域技术转移评测的标注员。任务：判断一条检索 query 与每个候选成果的技术适配度，"
        "按 0/1/2 打分。\n\n"
        f"{RUBRIC}\n"
        "候选成果是英文论文/综述；query 可能是中文或英文。只依据技术内容判断。\n"
        f"{QUERY_SCHEMA}"
    )
    body = "\n".join(
        _candidate_block(ach, i, max_abstract_chars)
        for i, ach in enumerate(candidates, 1)
    )
    user = (
        "## 检索 query\n"
        f"query_id：{query.get('query_id')}\n"
        f"query_text：{query.get('query_text')}\n"
        f"query_language：{query.get('query_language')}\n"
        f"query_type：{query.get('query_type')}\n"
        f"target_tech_field：{query.get('target_tech_field')}\n"
        f"备注：{query.get('notes') or '（无）'}\n\n"
        f"## 候选成果（共 {len(candidates)} 条）\n{body}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _demand_block(demand: dict) -> str:
    metrics = demand.get("technical_metrics") or []
    metric_text = "; ".join(
        f"{m.get('name')}={m.get('value')}{(' ' + m['unit']) if m.get('unit') else ''}"
        for m in metrics
        if isinstance(m, dict)
    ) or "（无）"
    return (
        f"demand_id：{demand.get('demand_id')}\n"
        f"标题：{demand.get('title')}\n"
        f"痛点：{demand.get('pain_point')}\n"
        f"期望方案：{demand.get('expected_solution')}\n"
        f"技术指标：{metric_text}\n"
        f"required_trl：{demand.get('required_trl')}\n"
        f"合作模式：{'; '.join(demand.get('cooperation_modes') or []) or '（无）'}\n"
        f"技术领域：{'; '.join(demand.get('tech_fields') or []) or '（无）'}\n"
        f"应用场景：{'; '.join(demand.get('application_scenarios') or []) or '（无）'}"
    )


def build_pair_messages(
    template: dict,
    demand: dict | None,
    achievement: dict,
    *,
    trl: int | None = None,
    max_abstract_chars: int = MAX_ABSTRACT_CHARS,
) -> list[dict]:
    system = (
        "你是新能源电池领域技术转移评测的标注员。任务：判断一条企业需求与一项成果的技术适配度，"
        "按 0/1/2 打分。\n\n"
        f"{RUBRIC}\n"
        f"{PAIR_SCHEMA}"
    )
    abstract = (achievement.get("abstract_original") or "").strip()
    if len(abstract) > max_abstract_chars:
        abstract = abstract[:max_abstract_chars] + "…"
    demand_text = _demand_block(demand) if demand else (
        f"demand_id：{template.get('demand_id')}\n标题：{template.get('demand_title')}"
    )
    user = (
        f"## 需求\n{demand_text}\n\n"
        "## 成果\n"
        f"achievement_id：{achievement.get('achievement_id')}\n"
        f"标题：{achievement.get('title_original')}\n"
        f"类型：{achievement.get('type') or 'unknown'}；年份：{achievement.get('publication_year') or 'unknown'}\n"
        f"关键词：{', '.join(achievement.get('keywords') or []) or '（无）'}\n"
        f"摘要：{abstract or '（缺失）'}\n"
        f"抽取 TRL：{trl if trl is not None else '（未提供）'}\n\n"
        f"模板标注：pair_source={template.get('pair_source')}，"
        f"hard_negative_type={template.get('hard_negative_type')}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# 解析与校验
# ---------------------------------------------------------------------------
def parse_query_response(
    raw: object,
    candidate_ids: list[str],
) -> tuple[list[dict], list[str], list[str]]:
    """返回 (合法项, 缺失候选 ID, 错误描述)。不做缺失补齐。"""
    if isinstance(raw, dict):
        items = raw.get("grades")
    elif isinstance(raw, list):
        items = raw
    else:
        return [], list(candidate_ids), ["输出不是 JSON 对象/数组"]
    if not isinstance(items, list):
        return [], list(candidate_ids), ["grades 不是数组"]

    allowed = set(candidate_ids)
    normalized: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"候选项不是对象：{item!r}")
            continue
        aid = str(item.get("achievement_id") or "").strip()
        if aid not in allowed:
            errors.append(f"未知 achievement_id：{aid!r}")
            continue
        if aid in seen:
            errors.append(f"重复 achievement_id：{aid}")
            continue
        grade = _as_grade(item.get("grade"))
        if grade is None:
            errors.append(f"{aid} 的 grade 非法：{item.get('grade')!r}")
            continue
        seen.add(aid)
        normalized.append(
            {
                "achievement_id": aid,
                "grade": grade,
                "confidence": _clamp_confidence(item.get("confidence")),
                "evidence": str(item.get("evidence") or "").strip(),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
    missing = [aid for aid in candidate_ids if aid not in seen]
    return normalized, missing, errors


def parse_pair_response(raw: object) -> tuple[dict | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["输出不是 JSON 对象"]
    grade = _as_grade(raw.get("grade"))
    if grade is None:
        return None, [f"grade 非法：{raw.get('grade')!r}"]
    return (
        {
            "grade": grade,
            "confidence": _clamp_confidence(raw.get("confidence")),
            "evidence": str(raw.get("evidence") or "").strip(),
            "rationale": str(raw.get("rationale") or "").strip(),
        },
        [],
    )


def _finalize_item(
    item: dict,
    achievement: dict,
    *,
    missing_reason: str | None = None,
) -> dict:
    evidence = item.get("evidence") or ""
    grounded = evidence_grounded(
        evidence,
        str(achievement.get("title_original") or ""),
        str(achievement.get("abstract_original") or ""),
    )
    confidence = _clamp_confidence(item.get("confidence"))
    if not evidence:
        confidence = min(confidence, 0.4)
    elif not grounded:
        confidence = min(confidence, 0.5)
    grade = int(item.get("grade") or 0)
    return {
        **item,
        "confidence": confidence,
        "evidence_grounded": grounded,
        "review_priority": review_priority(grade, confidence, evidence, grounded),
        "needs_review": bool(missing_reason),
        "review_reason": missing_reason or "",
    }


def extract_query(
    client: DashScopeClient,
    query: dict,
    candidates: list[dict],
    *,
    model: str | None,
    max_retries: int,
    max_abstract_chars: int,
    timeout: float,
) -> tuple[list[dict], int, list[str]]:
    """返回 (候选级结果, 重试次数, 错误列表)。缺失候选按 0 分 + needs_review 补齐。"""
    messages = build_query_messages(query, candidates, max_abstract_chars=max_abstract_chars)
    base = list(messages)
    by_id = {a["achievement_id"]: a for a in candidates}
    candidate_ids = [a["achievement_id"] for a in candidates]
    last_normalized: list[dict] = []
    last_errors: list[str] = []
    for attempt in range(max_retries + 1):
        raw = _call_chat_json(
            client,
            messages,
            model=model,
            max_tokens=QUERY_MAX_TOKENS,
            timeout=timeout,
        )
        normalized, missing, errors = parse_query_response(raw, candidate_ids)
        last_normalized, last_errors = normalized, errors
        if not missing and not errors:
            return [
                _finalize_item(item, by_id[item["achievement_id"]])
                for item in normalized
            ], attempt, []
        feedback = (
            "上一轮输出有问题，请修正后重新只输出 JSON：\n"
            + "\n".join(f"- {e}" for e in errors)
            + ("\n- 缺失候选：" + "; ".join(missing) if missing else "")
            + f"\n必须覆盖全部 {len(candidate_ids)} 个候选，每个恰好一条。"
        )
        messages = base + [
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {"role": "user", "content": feedback},
        ]

    # 重试耗尽：保留合法项，缺失/非法项按 0 分 + needs_review 补齐。
    done = {item["achievement_id"]: item for item in last_normalized}
    results: list[dict] = []
    for aid in candidate_ids:
        if aid in done:
            results.append(_finalize_item(done[aid], by_id[aid]))
        else:
            results.append(
                _finalize_item(
                    {
                        "achievement_id": aid,
                        "grade": 0,
                        "confidence": 0.0,
                        "evidence": "",
                        "rationale": "模型未返回该候选，需人工复核",
                    },
                    by_id[aid],
                    missing_reason="model_missing_candidate",
                )
            )
    errors = sorted(set(last_errors)) + (["retry_exhausted"] if not last_errors else [])
    return results, max_retries, errors


def extract_pair(
    client: DashScopeClient,
    template: dict,
    demand: dict | None,
    achievement: dict,
    *,
    trl: int | None,
    model: str | None,
    max_retries: int,
    max_abstract_chars: int,
    timeout: float,
) -> tuple[dict, int, list[str]]:
    messages = build_pair_messages(
        template, demand, achievement, trl=trl, max_abstract_chars=max_abstract_chars
    )
    base = list(messages)
    last_errors: list[str] = []
    for attempt in range(max_retries + 1):
        raw = _call_chat_json(
            client,
            messages,
            model=model,
            max_tokens=PAIR_MAX_TOKENS,
            timeout=timeout,
        )
        parsed, errors = parse_pair_response(raw)
        last_errors = errors
        if parsed is not None:
            return _finalize_item(parsed, achievement), attempt, []
        feedback = "上一轮输出有问题，请修正后重新只输出 JSON：\n" + "\n".join(
            f"- {e}" for e in errors
        )
        messages = base + [
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {"role": "user", "content": feedback},
        ]
    return (
        _finalize_item(
            {
                "grade": 0,
                "confidence": 0.0,
                "evidence": "",
                "rationale": "模型输出非法，需人工复核",
            },
            achievement,
            missing_reason="model_invalid_output",
        ),
        max_retries,
        sorted(set(last_errors)) or ["retry_exhausted"],
    )


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
QUERY_REVIEW_COLUMNS = [
    "query_id",
    "query_text",
    "query_language",
    "query_type",
    "target_tech_field",
    "achievement_id",
    "achievement_title",
    "achievement_type",
    "achievement_year",
    "abstract_excerpt",
    "llm_grade",
    "llm_confidence",
    "llm_evidence",
    "llm_rationale",
    "evidence_grounded",
    "review_priority",
    "human_grade",
    "human_note",
]

PAIR_REVIEW_COLUMNS = [
    "pair_id",
    "demand_id",
    "demand_title",
    "achievement_id",
    "achievement_title",
    "pair_source",
    "hard_negative_type",
    "llm_grade",
    "llm_confidence",
    "llm_evidence",
    "llm_rationale",
    "evidence_grounded",
    "review_priority",
    "human_grade",
    "human_note",
    "adjudication",
]


def build_query_review_rows(
    query: dict,
    candidates: list[dict],
    results: list[dict],
) -> list[dict]:
    by_id = {a["achievement_id"]: a for a in candidates}
    by_result = {r["achievement_id"]: r for r in results}
    rows: list[dict] = []
    for aid in query.get("candidate_achievement_ids") or []:
        ach = by_id.get(aid) or {}
        result = by_result.get(aid) or {}
        abstract = (ach.get("abstract_original") or "").strip()
        rows.append(
            {
                "query_id": query.get("query_id"),
                "query_text": query.get("query_text"),
                "query_language": query.get("query_language"),
                "query_type": query.get("query_type"),
                "target_tech_field": query.get("target_tech_field"),
                "achievement_id": aid,
                "achievement_title": ach.get("title_original") or "",
                "achievement_type": ach.get("type") or "",
                "achievement_year": ach.get("publication_year") or "",
                "abstract_excerpt": abstract[:600],
                "llm_grade": result.get("grade", ""),
                "llm_confidence": f"{result.get('confidence', 0):.3f}"
                if result
                else "",
                "llm_evidence": result.get("evidence", ""),
                "llm_rationale": result.get("rationale", ""),
                "evidence_grounded": result.get("evidence_grounded", ""),
                "review_priority": result.get("review_priority", ""),
                "human_grade": "",
                "human_note": "",
            }
        )
    return rows


def build_pair_review_rows(
    template: dict,
    result: dict,
) -> list[dict]:
    return [
        {
            "pair_id": template.get("pair_id"),
            "demand_id": template.get("demand_id"),
            "demand_title": template.get("demand_title"),
            "achievement_id": template.get("achievement_id"),
            "achievement_title": template.get("achievement_title"),
            "pair_source": template.get("pair_source"),
            "hard_negative_type": template.get("hard_negative_type"),
            "llm_grade": result.get("grade", ""),
            "llm_confidence": f"{result.get('confidence', 0):.3f}",
            "llm_evidence": result.get("evidence", ""),
            "llm_rationale": result.get("rationale", ""),
            "evidence_grounded": result.get("evidence_grounded", ""),
            "review_priority": result.get("review_priority", ""),
            "human_grade": "",
            "human_note": "",
            "adjudication": "",
        }
    ]


def _grade_counter(results: list[dict]) -> dict[str, int]:
    counts = {"0": 0, "1": 0, "2": 0}
    for result in results:
        counts[str(result.get("grade"))] = counts.get(str(result.get("grade")), 0) + 1
    return counts


def write_summary(
    path: Path,
    *,
    version: str,
    run_id: str,
    model: str,
    query_rows: list[dict],
    pair_rows: list[dict],
    failures: list[dict],
) -> None:
    q_high = sum(1 for r in query_rows if r.get("review_priority") == "high")
    p_high = sum(1 for r in pair_rows if r.get("review_priority") == "high")
    q_counts = {"0": 0, "1": 0, "2": 0}
    for r in query_rows:
        key = str(r.get("llm_grade"))
        q_counts[key] = q_counts.get(key, 0) + 1
    p_counts = {"0": 0, "1": 0, "2": 0}
    for r in pair_rows:
        key = str(r.get("llm_grade"))
        p_counts[key] = p_counts.get(key, 0) + 1
    lines = [
        f"# 评测集 LLM 预标结果（{version}）",
        "",
        f"- run_id：`{run_id}`",
        f"- 模型：`{model}`；prompt：`{PROMPT_VERSION}`",
        f"- query 候选草稿：{len(query_rows)} 行；高优先级 {q_high} 行；分数分布 {q_counts}",
        f"- pair 草稿：{len(pair_rows)} 行；高优先级 {p_high} 行；分数分布 {p_counts}",
        f"- 失败：{len(failures)} 条",
        "",
        "## 人工复核怎么做",
        "",
        "1. 打开**完整表** `query_candidates_review.csv`，用 `review_priority` 列筛选 high；"
        "`query_candidates_review_high.csv` 只是方便查看的子集，不能直接拿去合并。"
        "`human_grade` 留空表示接受 `llm_grade`，要改就填 0/1/2，并在 `human_note` 写一句理由。",
        "2. 高优先级看完后再抽查完整表的 normal 行，重点看 0 分是否有漏判。",
        "3. pair 用完整表 `pair_review.csv` 做同样的确认；human_grade 留空即接受草稿。",
        "4. 独立双标子集（4 条 query + 10 对 pair）必须另发不带 LLM 分数的空白表，"
        "第二人不能看草稿；否则 kappa 会虚高。",
        "5. 复核完成后保存**完整表**，运行 `scripts/data/apply_eval_annotations.py` 合并成正式文件；"
        "不要手工拼 `id:2;id:1`。",
        "",
        "## 口径提醒",
        "",
        "- “摘要没报告指标”不是“指标冲突”；2 分是技术适配度，不是要求候选满足需求全部 KPI。",
        "- 证据对不上的行（`evidence_grounded=False`）优先复核，模型可能看错或编造。",
        "- 预标不是人工标注；正式冻结前必须有 `human_grade` 复核记录。",
    ]
    if failures:
        lines += ["", "## 失败清单", ""]
        for failure in failures[:50]:
            lines.append(
                f"- `{failure.get('kind')}` `{failure.get('id')}`：{failure.get('error')}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 预标评测集，产出人工复核工作表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--queries", type=Path, default=None)
    parser.add_argument("--pairs", type=Path, default=None)
    parser.add_argument("--achievements", type=Path, default=None)
    parser.add_argument("--demands", type=Path, default=None)
    parser.add_argument("--labeled", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--only", choices=("all", "queries", "pairs"), default="all")
    parser.add_argument("--limit-queries", type=int, default=None)
    parser.add_argument("--limit-pairs", type=int, default=None)
    parser.add_argument("--max-abstract-chars", type=int, default=MAX_ABSTRACT_CHARS)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="单次 LLM 调用的硬超时（秒）；超时后跳过该条，可 --resume 重试",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只构造 prompt，不调用 API")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    version = args.version
    query_path = args.queries or (EVAL_DIR / f"retrieval_queries_{version}.jsonl")
    pair_path = args.pairs or (EVAL_DIR / f"pair_labels_{version}.jsonl")
    achievements_path = args.achievements or (
        PROCESSED_DIR / f"achievements_clean_{version}.jsonl"
    )
    demands_path = args.demands or (PROCESSED_DIR / f"demands_{version}.jsonl")
    labeled_path = args.labeled or (
        PROCESSED_DIR / f"achievements_labeled_{version}.jsonl"
    )
    out_dir = args.output_dir or (DATA_DIR / "interim" / "eval_prelabel" / version)

    for path in (query_path, pair_path, achievements_path, demands_path):
        if not path.exists():
            print(f"[错误] 缺少输入文件：{path}", file=sys.stderr)
            return 2
    if args.only in ("all", "queries") and not query_path.exists():
        print(f"[错误] 缺少 query 文件：{query_path}", file=sys.stderr)
        return 2
    if args.only in ("all", "pairs") and not pair_path.exists():
        print(f"[错误] 缺少 pair 文件：{pair_path}", file=sys.stderr)
        return 2

    queries = load_jsonl(query_path) if args.only in ("all", "queries") else []
    pairs = load_jsonl(pair_path) if args.only in ("all", "pairs") else []
    achievements = {a["achievement_id"]: a for a in load_jsonl(achievements_path)}
    demands = {d["demand_id"]: d for d in load_jsonl(demands_path)}
    trl_by_id: dict[str, int | None] = {}
    if labeled_path.exists():
        for record in load_jsonl(labeled_path):
            extraction = record.get("extraction") or {}
            trl_by_id[record.get("achievement_id")] = extraction.get("trl")

    if args.limit_queries is not None:
        queries = queries[: args.limit_queries]
    if args.limit_pairs is not None:
        pairs = pairs[: args.limit_pairs]

    out_dir.mkdir(parents=True, exist_ok=True)
    query_jsonl = out_dir / "query_prelabel.jsonl"
    pair_jsonl = out_dir / "pair_prelabel.jsonl"
    query_csv = out_dir / "query_candidates_review.csv"
    query_high_csv = out_dir / "query_candidates_review_high.csv"
    pair_csv = out_dir / "pair_review.csv"
    pair_high_csv = out_dir / "pair_review_high.csv"
    summary_path = out_dir / "review_summary.md"

    if not args.resume:
        existing = [p for p in (query_jsonl, pair_jsonl) if p.exists()]
        if existing:
            print("[错误] 输出已存在，拒绝覆盖：", file=sys.stderr)
            for path in existing:
                print(f"  {path}", file=sys.stderr)
            print("       删除后重跑，或加 --resume。", file=sys.stderr)
            return 2

    if args.dry_run:
        if queries:
            query = queries[0]
            candidates = [achievements[aid] for aid in query["candidate_achievement_ids"]]
            messages = build_query_messages(
                query, candidates, max_abstract_chars=args.max_abstract_chars
            )
            print("dry-run: query prompt")
            for message in messages:
                print(f"[{message['role']}] {len(message['content'])} chars")
        if pairs:
            template = pairs[0]
            achievement = achievements.get(template["achievement_id"], {})
            messages = build_pair_messages(
                template,
                demands.get(template["demand_id"]),
                achievement,
                trl=trl_by_id.get(template["achievement_id"]),
                max_abstract_chars=args.max_abstract_chars,
            )
            print("dry-run: pair prompt")
            for message in messages:
                print(f"[{message['role']}] {len(message['content'])} chars")
        return 0

    try:
        client = DashScopeClient()
    except LlmClientError as exc:
        print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
        print("       请先 `python scripts/common/llm_client.py --check` 核对 .env。", file=sys.stderr)
        return 2

    model = args.model or client.chat_model
    run_id = args.run_id or f"prelabel-{version}-{_now_tag()}"
    started = _now_utc()
    print(f"模型：{model}   prompt_version={PROMPT_VERSION}   run_id={run_id}")
    print(f"输出：{out_dir}\n")

    done_queries: set[str] = set()
    done_pairs: set[str] = set()
    if args.resume and query_jsonl.exists():
        done_queries = {r.get("query_id") for r in load_jsonl(query_jsonl)}
    if args.resume and pair_jsonl.exists():
        done_pairs = {r.get("pair_id") for r in load_jsonl(pair_jsonl)}

    query_records: list[dict] = load_jsonl(query_jsonl) if args.resume and query_jsonl.exists() else []
    pair_records: list[dict] = load_jsonl(pair_jsonl) if args.resume and pair_jsonl.exists() else []
    failures: list[dict] = []
    retries_used = 0

    for index, query in enumerate(queries, 1):
        qid = query.get("query_id")
        if qid in done_queries:
            continue
        candidates = [
            achievements[aid]
            for aid in query.get("candidate_achievement_ids") or []
            if aid in achievements
        ]
        if len(candidates) != len(query.get("candidate_achievement_ids") or []):
            missing = [
                aid
                for aid in query.get("candidate_achievement_ids") or []
                if aid not in achievements
            ]
            failures.append(
                {"kind": "query", "id": qid, "error": f"未知候选：{missing}"}
            )
            continue
        try:
            results, retries, errors = extract_query(
                client,
                query,
                candidates,
                model=model,
                max_retries=args.max_retries,
                max_abstract_chars=args.max_abstract_chars,
                timeout=args.timeout,
            )
            retries_used += retries
            record = {
                "query_id": qid,
                "query_text": query.get("query_text"),
                "query_language": query.get("query_language"),
                "query_type": query.get("query_type"),
                "target_tech_field": query.get("target_tech_field"),
                "candidates": results,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "run_id": run_id,
                "created_at": _now_utc(),
            }
            query_records.append(record)
            append_jsonl(query_jsonl, record)
            if errors:
                failures.append({"kind": "query", "id": qid, "error": "; ".join(errors)})
            print(
                f"[query {index}/{len(queries)}] {qid}  "
                f"grades={_grade_counter(results)}  retries={retries}  errors={errors}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 —— 单条失败不中断全量
            failures.append({"kind": "query", "id": qid, "error": str(exc)})
            print(f"[query {index}/{len(queries)}] {qid} 失败：{exc}", file=sys.stderr)

    for index, template in enumerate(pairs, 1):
        pid = template.get("pair_id")
        if pid in done_pairs:
            continue
        achievement = achievements.get(template.get("achievement_id"))
        if achievement is None:
            failures.append(
                {
                    "kind": "pair",
                    "id": pid,
                    "error": f"未知 achievement_id：{template.get('achievement_id')}",
                }
            )
            continue
        try:
            result, retries, errors = extract_pair(
                client,
                template,
                demands.get(template.get("demand_id")),
                achievement,
                trl=trl_by_id.get(template.get("achievement_id")),
                model=model,
                max_retries=args.max_retries,
                max_abstract_chars=args.max_abstract_chars,
                timeout=args.timeout,
            )
            retries_used += retries
            record = {
                "pair_id": pid,
                "demand_id": template.get("demand_id"),
                "demand_title": template.get("demand_title"),
                "achievement_id": template.get("achievement_id"),
                "achievement_title": template.get("achievement_title"),
                "pair_source": template.get("pair_source"),
                "hard_negative_type": template.get("hard_negative_type"),
                "result": result,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "run_id": run_id,
                "created_at": _now_utc(),
            }
            pair_records.append(record)
            append_jsonl(pair_jsonl, record)
            if errors:
                failures.append({"kind": "pair", "id": pid, "error": "; ".join(errors)})
            print(
                f"[pair {index}/{len(pairs)}] {pid}  grade={result.get('grade')}  "
                f"confidence={result.get('confidence')}  grounded={result.get('evidence_grounded')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"kind": "pair", "id": pid, "error": str(exc)})
            print(f"[pair {index}/{len(pairs)}] {pid} 失败：{exc}", file=sys.stderr)

    # 保证输出顺序与模板一致
    query_order = {q.get("query_id"): i for i, q in enumerate(queries)}
    pair_order = {p.get("pair_id"): i for i, p in enumerate(pairs)}
    query_records.sort(key=lambda r: query_order.get(r.get("query_id"), 10**9))
    pair_records.sort(key=lambda r: pair_order.get(r.get("pair_id"), 10**9))
    write_jsonl(query_jsonl, query_records) if query_records else None
    write_jsonl(pair_jsonl, pair_records) if pair_records else None

    query_rows: list[dict] = []
    for record in query_records:
        query = next((q for q in queries if q.get("query_id") == record["query_id"]), None)
        if not query:
            continue
        candidates = [
            achievements[aid]
            for aid in query.get("candidate_achievement_ids") or []
            if aid in achievements
        ]
        query_rows.extend(build_query_review_rows(query, candidates, record["candidates"]))
    pair_rows: list[dict] = []
    for record in pair_records:
        template = next((p for p in pairs if p.get("pair_id") == record["pair_id"]), None)
        if template:
            pair_rows.extend(build_pair_review_rows(template, record["result"]))

    if query_rows:
        write_csv(query_csv, query_rows, QUERY_REVIEW_COLUMNS)
        write_csv(
            query_high_csv,
            [r for r in query_rows if r.get("review_priority") == "high"],
            QUERY_REVIEW_COLUMNS,
        )
    if pair_rows:
        write_csv(pair_csv, pair_rows, PAIR_REVIEW_COLUMNS)
        write_csv(
            pair_high_csv,
            [r for r in pair_rows if r.get("review_priority") == "high"],
            PAIR_REVIEW_COLUMNS,
        )
    write_summary(
        summary_path,
        version=version,
        run_id=run_id,
        model=model,
        query_rows=query_rows,
        pair_rows=pair_rows,
        failures=failures,
    )

    manifest = {
        "run_id": run_id,
        "stage": "eval_prelabel",
        "sprint": SPRINT,
        "status": "success" if not failures else "partial",
        "dataset_version": version,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "started_at": started,
        "finished_at": _now_utc(),
        "input_paths": {
            "queries": _relpath(query_path),
            "pairs": _relpath(pair_path),
            "achievements": _relpath(achievements_path),
            "demands": _relpath(demands_path),
            "labeled": _relpath(labeled_path) if labeled_path.exists() else None,
        },
        "output_paths": {
            "query_prelabel": _relpath(query_jsonl) if query_records else None,
            "pair_prelabel": _relpath(pair_jsonl) if pair_records else None,
            "query_review": _relpath(query_csv) if query_rows else None,
            "pair_review": _relpath(pair_csv) if pair_rows else None,
            "summary": _relpath(summary_path),
        },
        "counts": {
            "queries": len(query_records),
            "query_candidates": len(query_rows),
            "pairs": len(pair_records),
            "failures": len(failures),
            "retries_used": retries_used,
        },
        "grade_distribution": {
            "queries": _grade_counter([c for r in query_records for c in r["candidates"]]),
            "pairs": _grade_counter([r["result"] for r in pair_records]),
        },
        "failures": failures,
        "config": {
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "only": args.only,
            "limit_queries": args.limit_queries,
            "limit_pairs": args.limit_pairs,
            "max_abstract_chars": args.max_abstract_chars,
            "max_retries": args.max_retries,
            "timeout": args.timeout,
        },
        "git_commit": _git_commit(),
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    }
    manifest_path = MANIFEST_DIR / f"prelabel_eval_{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n完成：query {len(query_records)} 条 / {len(query_rows)} 个候选；"
          f"pair {len(pair_records)} 对；失败 {len(failures)} 条")
    if query_rows:
        print(f"高优先级 query 复核项：{sum(1 for r in query_rows if r.get('review_priority') == 'high')}")
    if pair_rows:
        print(f"高优先级 pair 复核项：{sum(1 for r in pair_rows if r.get('review_priority') == 'high')}")
    print(f"复核说明：{summary_path}")
    print(f"清单：{manifest_path}")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
