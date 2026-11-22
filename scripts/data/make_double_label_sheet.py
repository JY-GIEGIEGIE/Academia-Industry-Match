#!/usr/bin/env python3
"""生成“独立双标”空白工作表（不含任何 LLM 草稿）。

S-09 要求 4 条 query + 10 对 pair 由第二人独立标注。用 prelabel 的复核表
做双标会让两个人共享同一份 LLM 偏差，kappa 会虚高；所以这里只放原始
query/需求/成果文本，不给模型分数。

默认双标集：
- query：q09—q12（4 条，覆盖中英文与两个技术方向）
- pair：pair_021—025（同领域 5 对）+ pair_046—050（跨领域 5 对）

用法：
  python scripts/data/make_double_label_sheet.py --version v0.1
  python scripts/data/make_double_label_sheet.py --version v0.1 \
    --queries q09,q10 --pairs pair_021,pair_022
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import DATA_DIR, EVAL_DIR, PROCESSED_DIR  # noqa: E402

DEFAULT_QUERIES = "q09,q10,q11,q12"
DEFAULT_PAIRS = (
    "pair_021,pair_022,pair_023,pair_024,pair_025,"
    "pair_046,pair_047,pair_048,pair_049,pair_050"
)

QUERY_COLUMNS = [
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
    "human_grade",
    "human_note",
]
PAIR_COLUMNS = [
    "pair_id",
    "demand_id",
    "demand_title",
    "demand_pain_point",
    "demand_expected_solution",
    "demand_metrics",
    "required_trl",
    "cooperation_modes",
    "achievement_id",
    "achievement_title",
    "achievement_type",
    "achievement_year",
    "abstract_excerpt",
    "human_grade",
    "human_note",
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


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _parse_ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _metrics_text(demand: dict) -> str:
    metrics = demand.get("technical_metrics") or []
    return "; ".join(
        f"{m.get('name')}={m.get('value')}{(' ' + m['unit']) if m.get('unit') else ''}"
        for m in metrics
        if isinstance(m, dict)
    )


def build_query_rows(
    queries: list[dict],
    selected_ids: set[str],
    achievements: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    missing: list[str] = []
    for query in queries:
        if query.get("query_id") not in selected_ids:
            continue
        for aid in query.get("candidate_achievement_ids") or []:
            ach = achievements.get(aid)
            if ach is None:
                missing.append(aid)
                continue
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
                    "abstract_excerpt": abstract[:800],
                    "human_grade": "",
                    "human_note": "",
                }
            )
    return rows, missing


def build_pair_rows(
    pairs: list[dict],
    selected_ids: set[str],
    achievements: dict[str, dict],
    demands: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    missing: list[str] = []
    for pair in pairs:
        if pair.get("pair_id") not in selected_ids:
            continue
        ach = achievements.get(pair.get("achievement_id"))
        demand = demands.get(pair.get("demand_id")) or {}
        if ach is None:
            missing.append(str(pair.get("achievement_id")))
            continue
        abstract = (ach.get("abstract_original") or "").strip()
        rows.append(
            {
                "pair_id": pair.get("pair_id"),
                "demand_id": pair.get("demand_id"),
                "demand_title": pair.get("demand_title") or demand.get("title"),
                "demand_pain_point": demand.get("pain_point") or "",
                "demand_expected_solution": demand.get("expected_solution") or "",
                "demand_metrics": _metrics_text(demand),
                "required_trl": demand.get("required_trl") or "",
                "cooperation_modes": ";".join(demand.get("cooperation_modes") or []),
                "achievement_id": pair.get("achievement_id"),
                "achievement_title": ach.get("title_original") or pair.get("achievement_title"),
                "achievement_type": ach.get("type") or "",
                "achievement_year": ach.get("publication_year") or "",
                "abstract_excerpt": abstract[:1200],
                "human_grade": "",
                "human_note": "",
                "adjudication": "",
                # 保留模板来源，方便复核是否覆盖同领域/跨领域
            }
        )
    return rows, missing


def write_readme(path: Path, *, query_ids: list[str], pair_ids: list[str]) -> None:
    text = f"""# 独立双标工作表

- query：{", ".join(query_ids)}（共 {len(query_ids)} 条）
- pair：{", ".join(pair_ids)}（共 {len(pair_ids)} 对）

## 标注规则

1. **不要打开** `data/interim/eval_prelabel/` 下的任何文件，也不要问另一位标注人；
   这是独立双标，看了 LLM 草稿或对方结果会让 kappa 虚高。
2. query 表：每条候选只看标题/摘要，按 0/1/2 打分。只填 1 或 2；不相关留空（统计时按 0）。
3. pair 表：按需求全文（痛点、期望方案、指标、required_trl、合作模式）和成果标题/摘要打分，
   0/1/2 都填；`human_note` 写一句理由，指出技术领域/场景/TRL/合作模式哪项匹配或不匹配。
4. 0/1/2 口径：
   - 2 = 技术领域一致；场景一致或兼容；TRL 差距 ≤2；合作模式可兼容；关键指标不冲突。
   - 1 = 领域一致但场景/TRL/合作模式有一项明显不匹配；或领域相邻但可迁移。
   - 0 = 领域不同且不可迁移；或关键约束冲突。
   - “摘要没报告某项指标”不等于“指标冲突”。
5. 填完另存为 `*_filled.csv`，不要覆盖空白表。

## 交付

把 `query_double_blank_filled.csv` 和 `pair_double_blank_filled.csv` 发给贾越；
用 `scripts/data/eval_kappa.py` 与主标对比，目标加权 kappa ≥0.6。
"""
    path.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成不带 LLM 草稿的独立双标空白工作表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1")
    parser.add_argument("--queries", default=DEFAULT_QUERIES)
    parser.add_argument("--pairs", default=DEFAULT_PAIRS)
    parser.add_argument("--queries-template", type=Path, default=None)
    parser.add_argument("--pairs-template", type=Path, default=None)
    parser.add_argument("--achievements", type=Path, default=None)
    parser.add_argument("--demands", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    version = args.version
    queries_path = args.queries_template or (
        EVAL_DIR / f"retrieval_queries_{version}.jsonl"
    )
    pairs_path = args.pairs_template or (EVAL_DIR / f"pair_labels_{version}.jsonl")
    achievements_path = args.achievements or (
        PROCESSED_DIR / f"achievements_clean_{version}.jsonl"
    )
    demands_path = args.demands or (PROCESSED_DIR / f"demands_{version}.jsonl")
    out_dir = args.output_dir or (DATA_DIR / "interim" / "double_label" / version)

    for path in (queries_path, pairs_path, achievements_path, demands_path):
        if not path.exists():
            print(f"[错误] 缺少输入文件：{path}", file=sys.stderr)
            return 2

    query_ids = _parse_ids(args.queries)
    pair_ids = _parse_ids(args.pairs)
    achievements = {a["achievement_id"]: a for a in load_jsonl(achievements_path)}
    demands = {d["demand_id"]: d for d in load_jsonl(demands_path)}
    queries = load_jsonl(queries_path)
    pairs = load_jsonl(pairs_path)

    query_rows, query_missing = build_query_rows(queries, set(query_ids), achievements)
    pair_rows, pair_missing = build_pair_rows(pairs, set(pair_ids), achievements, demands)
    if query_missing or pair_missing:
        print(f"[错误] 未知成果 ID：{sorted(set(query_missing + pair_missing))}", file=sys.stderr)
        return 2

    found_queries = sorted({row["query_id"] for row in query_rows})
    found_pairs = sorted({row["pair_id"] for row in pair_rows})
    missing_queries = sorted(set(query_ids) - set(found_queries))
    missing_pairs = sorted(set(pair_ids) - set(found_pairs))
    if missing_queries or missing_pairs:
        print(
            f"[错误] 模板中找不到：queries={missing_queries} pairs={missing_pairs}",
            file=sys.stderr,
        )
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    query_csv = out_dir / "query_double_blank.csv"
    pair_csv = out_dir / "pair_double_blank.csv"
    write_csv(query_csv, query_rows, QUERY_COLUMNS)
    write_csv(pair_csv, pair_rows, PAIR_COLUMNS)
    write_readme(
        out_dir / "README_双标说明.md",
        query_ids=found_queries,
        pair_ids=found_pairs,
    )

    print(f"query 双标：{len(found_queries)} 条 / {len(query_rows)} 个候选 -> {query_csv}")
    print(f"pair 双标：{len(found_pairs)} 对 -> {pair_csv}")
    print(f"说明：{out_dir / 'README_双标说明.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
