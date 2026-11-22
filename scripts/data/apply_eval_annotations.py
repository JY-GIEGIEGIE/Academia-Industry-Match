#!/usr/bin/env python3
"""把人工复核后的 query/pair 标注合并成正式评测文件。

输入二选一：
  --query-review CSV      prelabel_eval.py 产出的 query 候选表，人工已填 human_grade
  --pair-review CSV       prelabel_eval.py 产出的 pair 复核表，人工已填 human_grade
  --pair-final CSV        已经是最终标注的 pair 表（如黄欣悦提交的
                          pair_labels_v0.1_黄欣悦.csv）

输出（默认 data/eval/）：
  retrieval_queries_<version>.csv / .jsonl
  pair_labels_<version>.csv / .jsonl
  data/manifests/eval_annotation_summary_<version>.md

规则：
- 正式候选集以模板为准，绝不从复核表改候选 ID。
- `human_grade` 留空时，只有加 `--use-llm-when-blank` 才用 `llm_grade`；
  否则报错（避免把未复核的草稿当成人工标注）。
- query 的 `relevant_achievement_ids` 只含 1/2 分；`relevance_grades` 输出
  `id:2;id:1`（CSV）或对象（JSONL）。
- 写文件前做完整校验；有错误直接退出，不写半成品。

用法：
  # 先演练，不写文件
  python scripts/data/apply_eval_annotations.py --version v0.1 \
    --query-review data/interim/eval_prelabel/v0.1/query_candidates_review.csv \
    --dry-run

  # 正式写入
  python scripts/data/apply_eval_annotations.py --version v0.1 \
    --query-review data/interim/eval_prelabel/v0.1/query_candidates_review.csv \
    --pair-final "E:/SEM-软工管/pair_labels_v0.1_黄欣悦.csv" \
    --annotator "黄欣悦" --force
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import EVAL_DIR, MANIFEST_DIR  # noqa: E402

QUERY_COLUMNS = [
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
]
PAIR_COLUMNS = [
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
]


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_csv(path: Path) -> list[dict]:
    # Excel 在中文 Windows 上可能存成 GBK/ANSI；优先 UTF-8，失败再回退。
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"无法按 UTF-8/GBK 读取 {path}：{last_error}")


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


def _as_grade(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in (0, 1, 2):
        return value
    if isinstance(value, str) and value.strip() in ("0", "1", "2"):
        return int(value.strip())
    return None


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index_review(rows: list[dict], key_fields: tuple[str, ...]) -> dict[tuple, dict]:
    indexed: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(str(row.get(field) or "").strip() for field in key_fields)
        indexed[key] = row
    return indexed


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
def build_query_rows(
    templates: list[dict],
    review_rows: list[dict],
    *,
    annotator: str,
    use_llm_when_blank: bool,
) -> tuple[list[dict], list[dict], list[str], dict]:
    """返回 (正式行, 复核明细行, 错误, 统计)。正式行含 CSV/JSONL 共用的值。"""
    review = _index_review(review_rows, ("query_id", "achievement_id"))
    rows: list[dict] = []
    detail: list[dict] = []
    errors: list[str] = []
    stats = {
        "queries": 0,
        "candidates": 0,
        "human_overrides": 0,
        "llm_accepted": 0,
        "missing_review": 0,
        "relevant_counts": [],
        "grade_distribution": Counter(),
        "queries_without_2": 0,
        "queries_under_5_relevant": [],
    }

    for template in templates:
        qid = str(template.get("query_id") or "").strip()
        candidate_ids = list(template.get("candidate_achievement_ids") or [])
        if not candidate_ids:
            errors.append(f"{qid}: 模板没有 candidate_achievement_ids")
            continue

        grades: dict[str, int] = {}
        notes: list[str] = []
        for aid in candidate_ids:
            review_row = review.get((qid, aid))
            if review_row is None:
                stats["missing_review"] += 1
                errors.append(f"{qid}/{aid}: 复核表缺少该候选")
                continue
            human = review_row.get("human_grade")
            llm = review_row.get("llm_grade")
            if not _blank(human):
                grade = _as_grade(human)
                stats["human_overrides"] += 1
            elif use_llm_when_blank and not _blank(llm):
                grade = _as_grade(llm)
                stats["llm_accepted"] += 1
            else:
                errors.append(f"{qid}/{aid}: human_grade 为空，且未允许用 llm_grade")
                continue
            if grade is None:
                errors.append(f"{qid}/{aid}: 分数非法 human={human!r} llm={llm!r}")
                continue
            grades[aid] = grade
            stats["grade_distribution"][grade] += 1
            human_note = str(review_row.get("human_note") or "").strip()
            if human_note:
                notes.append(f"[{aid}] {human_note}")
            detail.append(
                {
                    "query_id": qid,
                    "achievement_id": aid,
                    "llm_grade": llm,
                    "human_grade": human,
                    "final_grade": grade,
                    "source": "human" if not _blank(human) else "llm",
                    "human_note": human_note,
                }
            )

        if len(grades) != len(candidate_ids):
            continue

        relevant_ids = [aid for aid in candidate_ids if grades[aid] in (1, 2)]
        grade_pairs = [f"{aid}:{grades[aid]}" for aid in candidate_ids]
        if not any(grade == 2 for grade in grades.values()):
            stats["queries_without_2"] += 1
        if len(relevant_ids) < 5:
            stats["queries_under_5_relevant"].append((qid, len(relevant_ids)))
        original_notes = str(template.get("notes") or "").strip()
        merged_notes = original_notes
        if notes:
            merged_notes = (merged_notes + " | " if merged_notes else "") + " | ".join(notes)
        rows.append(
            {
                "query_id": qid,
                "query_text": template.get("query_text"),
                "query_language": template.get("query_language"),
                "query_type": template.get("query_type"),
                "target_tech_field": template.get("target_tech_field"),
                "candidate_achievement_ids": candidate_ids,
                "relevant_achievement_ids": relevant_ids,
                "relevance_grades": grades,
                "annotator": annotator,
                "notes": merged_notes,
            }
        )
        stats["queries"] += 1
        stats["candidates"] += len(grades)
        stats["relevant_counts"].append(len(relevant_ids))

    return rows, detail, errors, stats


def _split_ids(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def _parse_grades_final(value: object) -> tuple[dict[str, int], str | None]:
    """解析人工 query 表的 relevance_grades：'id:2;id:1' 或对象。"""
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, str):
        items = []
        for segment in value.split(";"):
            segment = segment.strip()
            if not segment:
                continue
            if ":" not in segment:
                return {}, f"relevance_grades 片段缺 ':'：{segment!r}"
            aid, _, grade_text = segment.rpartition(":")
            items.append((aid.strip(), grade_text.strip()))
    else:
        return {}, "relevance_grades 不是字符串或对象"
    grades: dict[str, int] = {}
    for aid, grade_value in items:
        grade = _as_grade(grade_value)
        if not aid or grade is None:
            return {}, f"relevance_grades 非法：{aid!r}:{grade_value!r}"
        grades[str(aid)] = grade
    return grades, None


def build_query_rows_from_final(
    templates: list[dict],
    final_rows: list[dict],
    *,
    annotator: str,
) -> tuple[list[dict], list[str], dict]:
    """把黄欣悦式的最终 query CSV 合并成正式行。候选集/文本必须与模板一致。"""
    final = _index_review(final_rows, ("query_id",))
    rows: list[dict] = []
    errors: list[str] = []
    stats = {
        "source": "human_final",
        "queries": 0,
        "candidates": 0,
        "annotated_grades": 0,
        "human_overrides": 0,
        "llm_accepted": 0,
        "relevant_counts": [],
        "grade_distribution": Counter(),
        "queries_without_2": 0,
        "queries_under_5_relevant": [],
        "changed_fields": 0,
    }
    for template in templates:
        qid = str(template.get("query_id") or "").strip()
        source = final.get((qid,))
        if source is None:
            errors.append(f"{qid}: 最终标注缺少该 query")
            continue
        candidates = list(template.get("candidate_achievement_ids") or [])
        for field in ("query_text", "query_language", "query_type", "target_tech_field"):
            if str(source.get(field) or "").strip() != str(template.get(field) or "").strip():
                stats["changed_fields"] += 1
                errors.append(f"{qid}: {field} 与模板不一致")
        final_candidates = _split_ids(source.get("candidate_achievement_ids"))
        if final_candidates and final_candidates != candidates:
            stats["changed_fields"] += 1
            errors.append(f"{qid}: candidate_achievement_ids 与模板不一致")
            continue
        grades, grade_error = _parse_grades_final(source.get("relevance_grades"))
        if grade_error:
            errors.append(f"{qid}: {grade_error}")
            continue
        outside = [aid for aid in grades if aid not in candidates]
        if outside:
            errors.append(f"{qid}: relevance_grades 含候选集外 ID {outside[:3]}")
            continue
        relevant_ids = _split_ids(source.get("relevant_achievement_ids"))
        outside = [aid for aid in relevant_ids if aid not in candidates]
        if outside:
            errors.append(f"{qid}: relevant_achievement_ids 含候选集外 ID {outside[:3]}")
            continue
        relevant_from_grades = [aid for aid, grade in grades.items() if grade >= 1]
        if set(relevant_ids) != set(relevant_from_grades):
            errors.append(
                f"{qid}: relevant_achievement_ids 与 relevance_grades 不一致 "
                f"(list={len(relevant_ids)}, grades>=1={len(relevant_from_grades)})"
            )
            continue
        if not any(grade == 2 for grade in grades.values()):
            stats["queries_without_2"] += 1
        if len(relevant_ids) < 5:
            stats["queries_under_5_relevant"].append((qid, len(relevant_ids)))
        stats["queries"] += 1
        stats["candidates"] += len(candidates)
        stats["annotated_grades"] += len(grades)
        stats["human_overrides"] += len(grades)
        for grade in grades.values():
            stats["grade_distribution"][grade] += 1
        stats["relevant_counts"].append(len(relevant_ids))
        rows.append(
            {
                "query_id": qid,
                "query_text": template.get("query_text"),
                "query_language": template.get("query_language"),
                "query_type": template.get("query_type"),
                "target_tech_field": template.get("target_tech_field"),
                "candidate_achievement_ids": candidates,
                "relevant_achievement_ids": relevant_ids,
                "relevance_grades": grades,
                "annotator": str(source.get("annotator") or annotator).strip() or annotator,
                "notes": str(source.get("notes") or template.get("notes") or "").strip(),
            }
        )
    return rows, errors, stats


def query_csv_row(row: dict) -> dict:
    return {
        "query_id": row["query_id"],
        "query_text": row["query_text"],
        "query_language": row["query_language"],
        "query_type": row["query_type"],
        "target_tech_field": row["target_tech_field"],
        "candidate_achievement_ids": ";".join(row["candidate_achievement_ids"]),
        "relevant_achievement_ids": ";".join(row["relevant_achievement_ids"]),
        "relevance_grades": ";".join(
            f"{aid}:{grade}" for aid, grade in row["relevance_grades"].items()
        ),
        "annotator": row["annotator"],
        "notes": row["notes"],
    }


def query_jsonl_row(row: dict, version: str) -> dict:
    return {
        **row,
        "dataset_version": version,
    }


# ---------------------------------------------------------------------------
# Pair
# ---------------------------------------------------------------------------
def build_pair_rows_from_final(
    templates: list[dict],
    final_rows: list[dict],
    *,
    annotator: str,
) -> tuple[list[dict], list[str], dict]:
    final = _index_review(final_rows, ("pair_id",))
    rows: list[dict] = []
    errors: list[str] = []
    stats = {
        "pairs": 0,
        "grade_distribution": Counter(),
        "same_field_0": 0,
        "cross_field_1": 0,
        "missing_rationale": 0,
        "changed_ids": 0,
    }
    for template in templates:
        pid = str(template.get("pair_id") or "").strip()
        source = final.get((pid,))
        if source is None:
            errors.append(f"{pid}: 最终标注缺少该 pair")
            continue
        for field in ("demand_id", "achievement_id"):
            if str(source.get(field) or "").strip() != str(template.get(field) or "").strip():
                stats["changed_ids"] += 1
                errors.append(
                    f"{pid}: {field} 与模板不一致 "
                    f"({source.get(field)!r} != {template.get(field)!r})"
                )
        grade = _as_grade(source.get("relevance_grade"))
        if grade is None:
            errors.append(f"{pid}: relevance_grade 非法 {source.get('relevance_grade')!r}")
            continue
        rationale = str(source.get("rationale") or "").strip()
        if not rationale:
            stats["missing_rationale"] += 1
        if template.get("pair_source") == "same_field" and grade == 0:
            stats["same_field_0"] += 1
        if template.get("pair_source") == "cross_field" and grade == 1:
            stats["cross_field_1"] += 1
        stats["grade_distribution"][grade] += 1
        rows.append(
            {
                "pair_id": pid,
                "demand_id": template.get("demand_id"),
                "demand_title": template.get("demand_title"),
                "achievement_id": template.get("achievement_id"),
                "achievement_title": template.get("achievement_title"),
                "pair_source": template.get("pair_source"),
                "hard_negative_type": template.get("hard_negative_type"),
                "relevance_grade": grade,
                "rationale": rationale,
                "annotator": str(source.get("annotator") or annotator).strip() or annotator,
                "adjudication": str(source.get("adjudication") or "").strip(),
            }
        )
        stats["pairs"] += 1
    return rows, errors, stats


def build_pair_rows_from_review(
    templates: list[dict],
    review_rows: list[dict],
    *,
    annotator: str,
    use_llm_when_blank: bool,
) -> tuple[list[dict], list[dict], list[str], dict]:
    review = _index_review(review_rows, ("pair_id",))
    rows: list[dict] = []
    detail: list[dict] = []
    errors: list[str] = []
    stats = {
        "pairs": 0,
        "grade_distribution": Counter(),
        "same_field_0": 0,
        "cross_field_1": 0,
        "missing_rationale": 0,
        "human_overrides": 0,
        "llm_accepted": 0,
    }
    for template in templates:
        pid = str(template.get("pair_id") or "").strip()
        review_row = review.get((pid,))
        if review_row is None:
            errors.append(f"{pid}: 复核表缺少该 pair")
            continue
        human = review_row.get("human_grade")
        llm = review_row.get("llm_grade")
        if not _blank(human):
            grade = _as_grade(human)
            stats["human_overrides"] += 1
            source = "human"
        elif use_llm_when_blank and not _blank(llm):
            grade = _as_grade(llm)
            stats["llm_accepted"] += 1
            source = "llm"
        else:
            errors.append(f"{pid}: human_grade 为空，且未允许用 llm_grade")
            continue
        if grade is None:
            errors.append(f"{pid}: 分数非法 human={human!r} llm={llm!r}")
            continue
        human_note = str(review_row.get("human_note") or "").strip()
        rationale = human_note or str(review_row.get("llm_rationale") or "").strip()
        if not rationale:
            stats["missing_rationale"] += 1
        if template.get("pair_source") == "same_field" and grade == 0:
            stats["same_field_0"] += 1
        if template.get("pair_source") == "cross_field" and grade == 1:
            stats["cross_field_1"] += 1
        stats["grade_distribution"][grade] += 1
        row = {
            "pair_id": pid,
            "demand_id": template.get("demand_id"),
            "demand_title": template.get("demand_title"),
            "achievement_id": template.get("achievement_id"),
            "achievement_title": template.get("achievement_title"),
            "pair_source": template.get("pair_source"),
            "hard_negative_type": template.get("hard_negative_type"),
            "relevance_grade": grade,
            "rationale": rationale,
            "annotator": annotator,
            "adjudication": str(review_row.get("adjudication") or "").strip(),
        }
        rows.append(row)
        detail.append(
            {
                "pair_id": pid,
                "llm_grade": llm,
                "human_grade": human,
                "final_grade": grade,
                "source": source,
                "human_note": human_note,
            }
        )
        stats["pairs"] += 1
    return rows, detail, errors, stats


def pair_csv_row(row: dict) -> dict:
    return {
        "pair_id": row["pair_id"],
        "demand_id": row["demand_id"],
        "demand_title": row["demand_title"],
        "achievement_id": row["achievement_id"],
        "achievement_title": row["achievement_title"],
        "pair_source": row["pair_source"],
        "hard_negative_type": row["hard_negative_type"],
        "relevance_grade": str(row["relevance_grade"]),
        "rationale": row["rationale"],
        "annotator": row["annotator"],
        "adjudication": row["adjudication"],
    }


def pair_jsonl_row(row: dict, version: str) -> dict:
    return {**row, "dataset_version": version}


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def write_summary(
    path: Path,
    *,
    version: str,
    query_stats: dict | None,
    pair_stats: dict | None,
    query_paths: dict[str, Path],
    pair_paths: dict[str, Path],
    errors: list[str],
    use_llm_when_blank: bool,
) -> None:
    lines = [
        f"# 评测标注合并报告（{version}）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- query 复核：{'是' if query_stats else '否'}；pair 复核：{'是' if pair_stats else '否'}",
        f"- 空白 human_grade 是否回退 LLM 分：{'是（未完全人工复核）' if use_llm_when_blank else '否'}",
        "",
    ]
    if query_stats:
        counts = sorted(query_stats["relevant_counts"])
        lines += [
            "## 检索 query",
            "",
            f"- query 数：{query_stats['queries']}；候选判断：{query_stats['candidates']}",
        ]
        if query_stats.get("source") == "human_final":
            lines.append(
                f"- 来源：人工标注文件；显式分数 {query_stats['annotated_grades']} 个，"
                f"未标候选按 0 计 {query_stats['candidates'] - query_stats['annotated_grades']} 个"
            )
        else:
            lines.append(
                f"- 人工改分：{query_stats['human_overrides']}；"
                f"接受 LLM 分：{query_stats['llm_accepted']}"
            )
        lines += [
            f"- 分数分布：{dict(sorted(query_stats['grade_distribution'].items()))}",
            f"- 每条 query 相关数 min/median/max："
            f"{counts[0] if counts else 0}/{counts[len(counts)//2] if counts else 0}/"
            f"{counts[-1] if counts else 0}",
            f"- 没有 2 分的 query：{query_stats['queries_without_2']}/{query_stats['queries']}",
        ]
        if query_stats["queries_under_5_relevant"]:
            lines.append(
                "- 相关数 <5 的 query："
                + ", ".join(f"{qid}({n})" for qid, n in query_stats["queries_under_5_relevant"])
            )
        lines += ["", "输出文件：", ""]
        for label, file_path in query_paths.items():
            lines.append(f"- {label}: `{file_path}`  sha256=`{_sha256(file_path)}`")
        lines.append("")

    if pair_stats:
        lines += [
            "## pair",
            "",
            f"- pair 数：{pair_stats['pairs']}",
            f"- 分数分布：{dict(sorted(pair_stats['grade_distribution'].items()))}",
            f"- 同领域 0 分：{pair_stats['same_field_0']}；跨领域 1 分：{pair_stats['cross_field_1']}",
            f"- 缺 rationale：{pair_stats['missing_rationale']}",
        ]
        if pair_stats.get("human_overrides") is not None:
            lines.append(
                f"- 人工改分：{pair_stats['human_overrides']}；接受 LLM 分：{pair_stats['llm_accepted']}"
            )
        lines.append(
            "- 提醒：若没有 2 分，nDCG@10 会退化为二档；冻结前确认这是口径选择，不是漏标。"
        )
        lines += ["", "输出文件：", ""]
        for label, file_path in pair_paths.items():
            lines.append(f"- {label}: `{file_path}`  sha256=`{_sha256(file_path)}`")
        lines.append("")

    if errors:
        lines += ["## 错误", "", *[f"- {error}" for error in errors[:100]], ""]
    else:
        lines += ["## 错误", "", "- 无", ""]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="合并人工复核后的 query/pair 标注，生成正式评测文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1")
    parser.add_argument("--queries-template", type=Path, default=None)
    parser.add_argument("--pairs-template", type=Path, default=None)
    parser.add_argument("--query-review", type=Path, default=None)
    parser.add_argument(
        "--query-final",
        type=Path,
        default=None,
        help="已经是最终标注的 query 表（含 relevance_grades / relevant_achievement_ids）",
    )
    parser.add_argument("--pair-review", type=Path, default=None)
    parser.add_argument("--pair-final", type=Path, default=None)
    parser.add_argument("--annotator", default="人工复核")
    parser.add_argument(
        "--use-llm-when-blank",
        action="store_true",
        help="human_grade 留空时用 llm_grade；正式冻结前不建议",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--manifest-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有输出文件")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    version = args.version
    query_template_path = args.queries_template or (
        EVAL_DIR / f"retrieval_queries_{version}.jsonl"
    )
    pair_template_path = args.pairs_template or (
        EVAL_DIR / f"pair_labels_{version}.jsonl"
    )
    out_dir = args.out_dir or EVAL_DIR
    manifest_dir = args.manifest_dir or MANIFEST_DIR

    if not args.query_review and not args.query_final and not args.pair_review and not args.pair_final:
        print(
            "[错误] 至少提供一个输入：--query-review / --query-final / --pair-review / --pair-final",
            file=sys.stderr,
        )
        return 2
    if args.query_review and args.query_final:
        print("[错误] --query-review 与 --query-final 只能二选一", file=sys.stderr)
        return 2
    if args.pair_review and args.pair_final:
        print("[错误] --pair-review 与 --pair-final 只能二选一", file=sys.stderr)
        return 2

    query_outputs = {
        "csv": out_dir / f"retrieval_queries_{version}.csv",
        "jsonl": out_dir / f"retrieval_queries_{version}.jsonl",
    }
    pair_outputs = {
        "csv": out_dir / f"pair_labels_{version}.csv",
        "jsonl": out_dir / f"pair_labels_{version}.jsonl",
    }
    if not args.force and not args.dry_run:
        existing = [
            path
            for path in (*query_outputs.values(), *pair_outputs.values())
            if path.exists()
        ]
        if existing:
            print("[错误] 输出文件已存在，拒绝覆盖：", file=sys.stderr)
            for path in existing:
                print(f"  {path}", file=sys.stderr)
            print("       确认要覆盖时加 --force。", file=sys.stderr)
            return 2

    errors: list[str] = []
    query_rows: list[dict] = []
    pair_rows: list[dict] = []
    query_stats = None
    pair_stats = None

    if args.query_final:
        if not query_template_path.exists():
            print(f"[错误] 缺少 query 模板：{query_template_path}", file=sys.stderr)
            return 2
        templates = load_jsonl(query_template_path)
        final_rows = load_csv(args.query_final)
        query_rows, query_errors, query_stats = build_query_rows_from_final(
            templates, final_rows, annotator=args.annotator
        )
        errors.extend(query_errors)
        print(
            f"query：模板 {len(templates)} 条，最终标注 {len(final_rows)} 行，"
            f"生成 {len(query_rows)} 条；错误 {len(query_errors)}"
        )
        if query_errors and not args.force:
            print("[错误] query 校验未通过，未写文件。前 10 条：", file=sys.stderr)
            for error in query_errors[:10]:
                print(f"  - {error}", file=sys.stderr)
            return 2

    if args.query_review:
        if not query_template_path.exists():
            print(f"[错误] 缺少 query 模板：{query_template_path}", file=sys.stderr)
            return 2
        templates = load_jsonl(query_template_path)
        review_rows = load_csv(args.query_review)
        query_rows, query_detail, query_errors, query_stats = build_query_rows(
            templates,
            review_rows,
            annotator=args.annotator,
            use_llm_when_blank=args.use_llm_when_blank,
        )
        errors.extend(query_errors)
        print(
            f"query：模板 {len(templates)} 条，复核 {len(review_rows)} 行，"
            f"生成 {len(query_rows)} 条；错误 {len(query_errors)}"
        )
        if query_errors and not args.force:
            print("[错误] query 校验未通过，未写文件。前 10 条：", file=sys.stderr)
            for error in query_errors[:10]:
                print(f"  - {error}", file=sys.stderr)
            return 2

    if args.pair_final:
        if not pair_template_path.exists():
            print(f"[错误] 缺少 pair 模板：{pair_template_path}", file=sys.stderr)
            return 2
        templates = load_jsonl(pair_template_path)
        final_rows = load_csv(args.pair_final)
        pair_rows, pair_errors, pair_stats = build_pair_rows_from_final(
            templates, final_rows, annotator=args.annotator
        )
        errors.extend(pair_errors)
        print(
            f"pair：模板 {len(templates)} 对，最终标注 {len(final_rows)} 行，"
            f"生成 {len(pair_rows)} 对；错误 {len(pair_errors)}"
        )
        if pair_errors and not args.force:
            print("[错误] pair 校验未通过，未写文件。前 10 条：", file=sys.stderr)
            for error in pair_errors[:10]:
                print(f"  - {error}", file=sys.stderr)
            return 2

    if args.pair_review:
        if not pair_template_path.exists():
            print(f"[错误] 缺少 pair 模板：{pair_template_path}", file=sys.stderr)
            return 2
        templates = load_jsonl(pair_template_path)
        review_rows = load_csv(args.pair_review)
        pair_rows, pair_detail, pair_errors, pair_stats = build_pair_rows_from_review(
            templates,
            review_rows,
            annotator=args.annotator,
            use_llm_when_blank=args.use_llm_when_blank,
        )
        errors.extend(pair_errors)
        print(
            f"pair：模板 {len(templates)} 对，复核 {len(review_rows)} 行，"
            f"生成 {len(pair_rows)} 对；错误 {len(pair_errors)}"
        )
        if pair_errors and not args.force:
            print("[错误] pair 校验未通过，未写文件。前 10 条：", file=sys.stderr)
            for error in pair_errors[:10]:
                print(f"  - {error}", file=sys.stderr)
            return 2

    if errors and not args.force:
        print(f"[错误] 共 {len(errors)} 个校验错误，未写文件。", file=sys.stderr)
        return 2

    if args.dry_run:
        if query_stats:
            print(f"  query 分数分布：{dict(sorted(query_stats['grade_distribution'].items()))}")
            print(f"  query 每条约相关数：{query_stats['relevant_counts']}")
        if pair_stats:
            print(f"  pair 分数分布：{dict(sorted(pair_stats['grade_distribution'].items()))}")
        print("dry-run：未写文件。")
        return 0 if not errors else 1

    if query_rows:
        write_csv(
            query_outputs["csv"],
            [query_csv_row(row) for row in query_rows],
            QUERY_COLUMNS,
        )
        write_jsonl(
            query_outputs["jsonl"],
            [query_jsonl_row(row, version) for row in query_rows],
        )
        print(f"  -> {query_outputs['csv']}\n  -> {query_outputs['jsonl']}")
    if pair_rows:
        write_csv(
            pair_outputs["csv"],
            [pair_csv_row(row) for row in pair_rows],
            PAIR_COLUMNS,
        )
        write_jsonl(
            pair_outputs["jsonl"],
            [pair_jsonl_row(row, version) for row in pair_rows],
        )
        print(f"  -> {pair_outputs['csv']}\n  -> {pair_outputs['jsonl']}")

    summary_path = manifest_dir / f"eval_annotation_summary_{version}.md"
    write_summary(
        summary_path,
        version=version,
        query_stats=query_stats,
        pair_stats=pair_stats,
        query_paths={
            label: path for label, path in query_outputs.items() if path.exists()
        },
        pair_paths={
            label: path for label, path in pair_outputs.items() if path.exists()
        },
        errors=errors,
        use_llm_when_blank=args.use_llm_when_blank,
    )
    print(f"报告：{summary_path}")
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
