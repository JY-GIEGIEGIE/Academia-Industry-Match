#!/usr/bin/env python3
"""计算两套标注的加权 Cohen's kappa，并输出可复核报告。

支持两种输入：
- query 复核表：按 (query_id, achievement_id) 对齐；未填的候选可按 0 分处理。
- pair 复核表 / 最终表：按 pair_id 对齐。

典型用法：
  # 两个人工标注人：主标 vs 独立双标
  python scripts/data/eval_kappa.py \
    --primary data/interim/.../query_candidates_review.csv \
    --secondary data/interim/.../query_double_blank_filled.csv \
    --kind queries --output data/manifests/kappa_query_v0.1.md

  # LLM 预标 vs 人工：primary 用 llm_grade
  python scripts/data/eval_kappa.py \
    --primary data/interim/.../pair_review.csv \
    --secondary "E:/SEM-软工管/pair_labels_v0.1_黄欣悦.csv" \
    --kind pairs --use-llm-when-blank

口径：
- 加权 Cohen's kappa，默认线性权重（|i-j|/2），可用 --weights quadratic。
- kappa ≥0.6 为本次验收目标；n<30 时数值不稳定，报告里会标注。
- 同分率（observed agreement）单独报告，避免只看 kappa。
"""

from __future__ import annotations

import argparse
import csv
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

from config import MANIFEST_DIR  # noqa: E402

CATEGORIES = (0, 1, 2)


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


def _blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _as_grade(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in CATEGORIES:
        return value
    if isinstance(value, str) and value.strip() in ("0", "1", "2"):
        return int(value.strip())
    return None


def _split_ids(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return []


def _parse_grades_value(value: object) -> dict[str, int]:
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, str):
        items = []
        for segment in value.split(";"):
            segment = segment.strip()
            if not segment or ":" not in segment:
                continue
            aid, _, grade_text = segment.rpartition(":")
            items.append((aid.strip(), grade_text.strip()))
    else:
        return {}
    grades: dict[str, int] = {}
    for aid, grade_value in items:
        grade = _as_grade(grade_value)
        if aid and grade is not None:
            grades[str(aid)] = grade
    return grades


def expand_query_rows(rows: list[dict]) -> list[dict]:
    """把一行一 query 的 relevance_grades 展开成一行一候选。

    已经是逐候选行（含 achievement_id）的表原样返回。
    """
    if not rows or "achievement_id" in rows[0]:
        return rows
    expanded: list[dict] = []
    for row in rows:
        if "query_id" not in row:
            continue
        candidates = _split_ids(row.get("candidate_achievement_ids"))
        grades = _parse_grades_value(row.get("relevance_grades"))
        for aid in candidates:
            expanded.append(
                {
                    **row,
                    "achievement_id": aid,
                    "human_grade": grades.get(aid, 0),
                }
            )
    return expanded


def detect_kind(rows: list[dict]) -> str:
    if not rows:
        raise ValueError("空表无法判断类型")
    if "query_id" in rows[0] and "achievement_id" in rows[0]:
        return "queries"
    if "pair_id" in rows[0]:
        return "pairs"
    raise ValueError("无法判断类型：缺少 query_id+achievement_id 或 pair_id")


def key_for(row: dict, kind: str) -> tuple[str, ...]:
    if kind == "queries":
        return (
            str(row.get("query_id") or "").strip(),
            str(row.get("achievement_id") or "").strip(),
        )
    return (str(row.get("pair_id") or "").strip(),)


def human_grade_from_row(row: dict) -> int | None:
    for field in ("human_grade", "relevance_grade"):
        if not _blank(row.get(field)):
            return _as_grade(row.get(field))
    return None


def llm_grade_from_row(row: dict) -> int | None:
    return _as_grade(row.get("llm_grade"))


def primary_grade(
    row: dict,
    *,
    use_llm_when_blank: bool,
    blank_as_zero: bool,
) -> int | None:
    grade = human_grade_from_row(row)
    if grade is not None:
        return grade
    if use_llm_when_blank:
        grade = llm_grade_from_row(row)
        if grade is not None:
            return grade
    return 0 if blank_as_zero else None


def secondary_grade(
    row: dict,
    *,
    blank_as_zero: bool,
    use_llm_when_blank: bool = False,
) -> int | None:
    grade = human_grade_from_row(row)
    if grade is not None:
        return grade
    if use_llm_when_blank:
        grade = llm_grade_from_row(row)
        if grade is not None:
            return grade
    return 0 if blank_as_zero else None


def weighted_kappa(
    primary: list[int],
    secondary: list[int],
    *,
    weights: str = "linear",
) -> dict:
    """三档 0/1/2 的加权 Cohen's kappa。"""
    if len(primary) != len(secondary):
        raise ValueError("两套标注长度不一致")
    n = len(primary)
    if n == 0:
        return {
            "n": 0,
            "observed_agreement": None,
            "expected_agreement": None,
            "kappa": None,
            "confusion": [[0, 0, 0] for _ in range(3)],
            "note": "没有可比较的条目",
        }

    confusion = [[0 for _ in CATEGORIES] for _ in CATEGORIES]
    for a, b in zip(primary, secondary):
        confusion[a][b] += 1
    row_sums = [sum(confusion[i]) for i in range(3)]
    col_sums = [sum(confusion[i][j] for i in range(3)) for j in range(3)]

    def weight(i: int, j: int) -> float:
        distance = abs(i - j) / 2.0
        if weights == "quadratic":
            return 1.0 - distance * distance
        return 1.0 - distance

    observed = sum(weight(i, j) * confusion[i][j] for i in range(3) for j in range(3)) / n
    expected = (
        sum(
            weight(i, j) * row_sums[i] * col_sums[j] / n
            for i in range(3)
            for j in range(3)
        )
        / n
    )
    if abs(1.0 - expected) < 1e-12:
        kappa = None
        note = "期望一致率=1（两套标注都没有方差），kappa 无定义"
    else:
        kappa = (observed - expected) / (1.0 - expected)
        note = ""
    return {
        "n": n,
        "observed_agreement": round(observed, 6),
        "expected_agreement": round(expected, 6),
        "kappa": None if kappa is None else round(kappa, 6),
        "confusion": confusion,
        "note": note,
    }


def interpretation(kappa: float | None) -> str:
    if kappa is None:
        return "无定义"
    if kappa < 0:
        return "差（低于随机）"
    if kappa < 0.21:
        return "轻微"
    if kappa < 0.41:
        return "一般"
    if kappa < 0.61:
        return "中等"
    if kappa < 0.81:
        return "较强"
    return "几乎完全一致"


def compare(
    primary_rows: list[dict],
    secondary_rows: list[dict],
    *,
    kind: str,
    weights: str,
    use_llm_when_blank: bool,
    blank_as_zero: bool,
) -> dict:
    primary = {key_for(row, kind): row for row in primary_rows}
    secondary = {key_for(row, kind): row for row in secondary_rows}
    common = sorted(set(primary) & set(secondary))
    only_primary = sorted(set(primary) - set(secondary))
    only_secondary = sorted(set(secondary) - set(primary))

    p_grades: list[int] = []
    s_grades: list[int] = []
    skipped: list[dict] = []
    for key in common:
        p = primary_grade(
            primary[key],
            use_llm_when_blank=use_llm_when_blank,
            blank_as_zero=blank_as_zero,
        )
        s = secondary_grade(
            secondary[key],
            blank_as_zero=blank_as_zero,
            use_llm_when_blank=use_llm_when_blank,
        )
        if p is None or s is None:
            skipped.append({"key": key, "primary": p, "secondary": s})
            continue
        p_grades.append(p)
        s_grades.append(s)

    result = weighted_kappa(p_grades, s_grades, weights=weights)
    result.update(
        {
            "kind": kind,
            "weights": weights,
            "common_keys": len(common),
            "only_primary": len(only_primary),
            "only_secondary": len(only_secondary),
            "skipped": len(skipped),
            "primary_distribution": dict(sorted(Counter(p_grades).items())),
            "secondary_distribution": dict(sorted(Counter(s_grades).items())),
            "only_primary_examples": [list(key) for key in only_primary[:5]],
            "only_secondary_examples": [list(key) for key in only_secondary[:5]],
        }
    )

    # LLM vs 第二个标注人：优先从 primary 取 llm_grade，否则从 secondary 取。
    llm_pairs: list[tuple[int, int]] = []
    for key in common:
        p_row, s_row = primary[key], secondary[key]
        human = human_grade_from_row(s_row)
        if human is None:
            human = human_grade_from_row(p_row)
        llm = llm_grade_from_row(p_row)
        if llm is None:
            llm = llm_grade_from_row(s_row)
        if human is not None and llm is not None:
            llm_pairs.append((llm, human))
    if llm_pairs:
        llm_result = weighted_kappa(
            [pair[0] for pair in llm_pairs],
            [pair[1] for pair in llm_pairs],
            weights=weights,
        )
        result["llm_vs_human"] = llm_result
    else:
        result["llm_vs_human"] = None
    return result


def render_markdown(result: dict, primary_path: Path, secondary_path: Path) -> str:
    lines = [
        "# 标注一致性报告（加权 Cohen's kappa）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 类型：{result['kind']}；权重：{result['weights']}",
        f"- primary：`{primary_path}`",
        f"- secondary：`{secondary_path}`",
        "",
        "## 主结果",
        "",
        f"- 可比较条目：{result['n']}（共同 key {result['common_keys']}；"
        f"仅 primary {result['only_primary']}；仅 secondary {result['only_secondary']}；"
        f"跳过 {result['skipped']}）",
        f"- 同分率：{result['observed_agreement']}",
        f"- 期望一致率：{result['expected_agreement']}",
        f"- 加权 kappa：**{result['kappa']}**（{interpretation(result['kappa'])}）",
        f"- 分数分布：primary {result['primary_distribution']}；"
        f"secondary {result['secondary_distribution']}",
    ]
    if result.get("note"):
        lines.append(f"- 备注：{result['note']}")
    if result["n"] < 30:
        lines.append("- ⚠ n<30，kappa 数值不稳定，需结合逐条分歧一起看。")
    if result["only_primary_examples"]:
        lines.append(f"- 仅 primary 示例：{result['only_primary_examples']}")
    if result["only_secondary_examples"]:
        lines.append(f"- 仅 secondary 示例：{result['only_secondary_examples']}")

    lines += ["", "## 混淆矩阵（行=primary，列=secondary）", ""]
    lines.append("| primary \\ secondary | 0 | 1 | 2 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for i, row in enumerate(result["confusion"]):
        lines.append(f"| {i} | {row[0]} | {row[1]} | {row[2]} |")

    if result.get("llm_vs_human"):
        llm = result["llm_vs_human"]
        lines += [
            "",
            "## LLM 预标 vs 人工（参考）",
            "",
            f"- 可比较条目：{llm['n']}",
            f"- 同分率：{llm['observed_agreement']}",
            f"- 加权 kappa：**{llm['kappa']}**（{interpretation(llm['kappa'])}）",
        ]
        if llm.get("note"):
            lines.append(f"- 备注：{llm['note']}")
        lines += ["", "| LLM \\ 人工 | 0 | 1 | 2 |", "| --- | ---: | ---: | ---: |"]
        for i, row in enumerate(llm["confusion"]):
            lines.append(f"| {i} | {row[0]} | {row[1]} | {row[2]} |")
        lines += [
            "",
            "注意：LLM-人工一致性只用于评估预标质量，不能替代人工-人工 kappa 的验收。",
        ]

    lines += [
        "",
        "## 口径",
        "",
        "- 加权 Cohen's kappa：线性权重 1-|i-j|/2；二次权重 1-((i-j)/2)^2。",
        "- query 未标注候选默认按 0 分处理（可用 --no-blank-as-zero 关闭）。",
        "- kappa ≥0.6 为验收目标；低于 0.6 先检查 0/1/2 边界定义，再重标分歧项。",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="计算两套标注的加权 Cohen's kappa",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--kind", choices=("auto", "queries", "pairs"), default="auto")
    parser.add_argument(
        "--expand-queries",
        action="store_true",
        help="把一行一 query 的 relevance_grades 展开成逐候选行（用于正式 query 表 vs 双标表）",
    )
    parser.add_argument("--weights", choices=("linear", "quadratic"), default="linear")
    parser.add_argument(
        "--use-llm-when-blank",
        action="store_true",
        help="primary 的 human_grade 为空时用 llm_grade（LLM vs 人工对比时用）",
    )
    parser.add_argument(
        "--blank-as-zero",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="未填分数按 0 分处理",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    for path in (args.primary, args.secondary):
        if not path.exists():
            print(f"[错误] 缺少输入文件：{path}", file=sys.stderr)
            return 2
    primary_rows = load_csv(args.primary)
    secondary_rows = load_csv(args.secondary)
    if args.expand_queries:
        primary_rows = expand_query_rows(primary_rows)
        secondary_rows = expand_query_rows(secondary_rows)
    kind = args.kind
    if kind == "auto":
        try:
            kind = detect_kind(primary_rows)
            if detect_kind(secondary_rows) != kind:
                raise ValueError("两个文件的类型不一致")
        except ValueError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 2

    result = compare(
        primary_rows,
        secondary_rows,
        kind=kind,
        weights=args.weights,
        use_llm_when_blank=args.use_llm_when_blank,
        blank_as_zero=args.blank_as_zero,
    )
    markdown = render_markdown(result, args.primary, args.secondary)
    print(markdown)
    output = args.output or (
        MANIFEST_DIR
        / f"kappa_{kind}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"报告：{output}")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
