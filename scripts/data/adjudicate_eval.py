#!/usr/bin/env python3
"""把双标分歧按“差距口径”分类裁决，并写回正式评测文件。

输入：
  data/interim/s09_review/adjudication_39.csv  （双标分歧逐条表）

分类规则（本次 v0.1 固定）：
  Q1a query 硬约束（单晶/≤5MPa/空气稳定性/具体容量或首效）未被候选直接覆盖 -> 1
  Q1b 综述/二次研究，主题覆盖但无直接数据 -> 1
  Q2  相邻领域/不同材料体系，但方法或机理可迁移 -> 1
  Q3  推断性适配，摘要无直接证据 -> 1
  P1  综述/TRL差距>2 -> 1
  P2  需求指定材料与成果材料硬冲突 -> 0
  P3  相邻/可迁移但非直接技术 -> 1

输出：
  data/manifests/eval_adjudication_v0.1.csv / .md
  data/manifests/eval_annotation_summary_v0.1.md
  data/eval/retrieval_queries_v0.1.csv / .jsonl
  data/eval/pair_labels_v0.1.csv / .jsonl
  data/manifests/dataset_v0.1.json 的 evaluation 块

用法：
  python scripts/data/adjudicate_eval.py --dry-run
  python scripts/data/adjudicate_eval.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import EVAL_DIR, MANIFEST_DIR  # noqa: E402

VERSION = "v0.1"
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

CATEGORY_RULES = {
    "Q1a": "query 硬约束（单晶/≤5MPa/空气稳定性/具体容量或首效）未被候选直接覆盖；维持1",
    "Q1b": "综述/二次研究，主题覆盖但无直接数据；维持1",
    "Q2": "相邻领域/不同材料体系，但方法或机理可迁移；按规范=1",
    "Q3": "推断性适配，摘要无直接证据；改1",
    "P1": "综述/TRL差距>2，不能给2；维持1",
    "P2": "需求指定NCM，成果为LFP，材料体系硬冲突；维持0",
    "P3": "经济性分析属相邻决策支持，可迁移；维持1",
}


def load_csv(path: Path) -> list[dict]:
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


def parse_grades(text: object) -> dict[str, int]:
    grades: dict[str, int] = {}
    for segment in str(text or "").split(";"):
        segment = segment.strip()
        if not segment or ":" not in segment:
            continue
        achievement_id, _, grade_text = segment.rpartition(":")
        try:
            grade = int(grade_text.strip())
        except ValueError:
            continue
        if grade in (0, 1, 2):
            grades[achievement_id.strip()] = grade
    return grades


def split_ids(text: object) -> list[str]:
    return [part.strip() for part in str(text or "").split(";") if part.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(row: dict) -> tuple[str, int]:
    if row["kind"] == "query":
        human = int(row["human_grade"])
        user = int(row["user_grade"])
        title = str(row.get("title") or "").lower()
        note = str(row.get("user_note") or "")
        if human == 0 and user == 1:
            return "Q2", 1
        if human == 0 and user == 2:
            return "Q3", 1
        if human == 1 and user == 2:
            if any(
                keyword in title
                for keyword in (
                    "review",
                    "perspective",
                    "revisiting",
                    "progress",
                    "reappraisal",
                    "fundamentals",
                )
            ) or "综述" in note:
                return "Q1b", 1
            if any(
                keyword in note
                for keyword in ("天然适配", "适配低堆叠压力", "复合电解质路线")
            ):
                return "Q3", 1
            return "Q1a", 1
        return "OTHER", human
    if row["id"] == "pair_021":
        return "P1", 1
    if row["id"] == "pair_022":
        return "P2", 0
    if row["id"] == "pair_025":
        return "P3", 1
    return "OTHER", int(row["human_grade"])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    adjudication_path = args.adjudication
    if not adjudication_path.exists():
        print(f"[错误] 缺少裁决表：{adjudication_path}", file=sys.stderr)
        return 2
    raw = load_csv(adjudication_path)
    for row in raw:
        category, final = classify(row)
        row["category"] = category
        row["category_rule"] = CATEGORY_RULES.get(category, "")
        row["final_grade"] = final
        row["decision_note"] = (
            f"第二标注人判{row['user_grade']}；按{category}裁决为{final}"
        )

    query_path = EVAL_DIR / f"retrieval_queries_{VERSION}.csv"
    pair_path = EVAL_DIR / f"pair_labels_{VERSION}.csv"
    query_rows = load_csv(query_path)
    pair_rows = load_csv(pair_path)
    query_adjudication: dict[str, list[dict]] = defaultdict(list)
    pair_adjudication: dict[str, dict] = {}
    for row in raw:
        if row["kind"] == "query":
            query_adjudication[row["id"]].append(row)
        else:
            pair_adjudication[row["id"]] = row

    changes: Counter = Counter()
    for row in query_rows:
        query_id = row["query_id"]
        candidates = split_ids(row["candidate_achievement_ids"])
        grades = parse_grades(row["relevance_grades"])
        changed = 0
        for adjudication in query_adjudication.get(query_id, []):
            old = grades.get(adjudication["achievement_id"], 0)
            new = int(adjudication["final_grade"])
            if old == new:
                continue
            changed += 1
            if new == 0:
                grades.pop(adjudication["achievement_id"], None)
            else:
                grades[adjudication["achievement_id"]] = new
        if changed:
            changes[query_id] = changed
            row["notes"] = (
                str(row.get("notes") or "").rstrip()
                + f" [双标裁决: {changed}条0→1]"
            ).strip()
        row["relevant_achievement_ids"] = ";".join(
            aid for aid in candidates if grades.get(aid, 0) >= 1
        )
        row["relevance_grades"] = ";".join(
            f"{aid}:{grades[aid]}" for aid in candidates if aid in grades
        )

    for row in pair_rows:
        adjudication = pair_adjudication.get(row["pair_id"])
        if adjudication:
            row["relevance_grade"] = str(int(adjudication["final_grade"]))
            row["adjudication"] = adjudication["decision_note"]

    # 统计
    query_dist: Counter = Counter()
    query_relevant: list[tuple[str, int]] = []
    for row in query_rows:
        grades = parse_grades(row["relevance_grades"])
        query_dist.update(grades.values())
        query_relevant.append((row["query_id"], sum(1 for g in grades.values() if g >= 1)))
    pair_dist = Counter(int(row["relevance_grade"]) for row in pair_rows)
    category_counts = Counter(row["category"] for row in raw)

    print(f"分类：{dict(category_counts)}")
    print(f"query 改动：{dict(changes)}，共 {sum(changes.values())} 条 0→1")
    print(f"query 最终分布：{dict(sorted(query_dist.items()))}；相关数：{query_relevant}")
    print(f"pair 最终分布：{dict(sorted(pair_dist.items()))}")

    if args.dry_run:
        print("dry-run：未写文件。")
        return 0

    # 写裁决记录
    adjudication_columns = [
        "kind",
        "id",
        "achievement_id",
        "title",
        "demand_or_query",
        "human_grade",
        "user_grade",
        "llm_grade",
        "category",
        "category_rule",
        "final_grade",
        "decision_note",
        "user_note",
        "human_note",
    ]
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    adjudication_csv = MANIFEST_DIR / "eval_adjudication_v0.1.csv"
    write_csv(adjudication_csv, raw, adjudication_columns)

    # 写正式评测文件
    write_csv(query_path, query_rows, QUERY_COLUMNS)
    query_jsonl: list[dict] = []
    for row in query_rows:
        candidates = split_ids(row["candidate_achievement_ids"])
        grades = parse_grades(row["relevance_grades"])
        query_jsonl.append(
            {
                "query_id": row["query_id"],
                "query_text": row["query_text"],
                "query_language": row["query_language"],
                "query_type": row["query_type"],
                "target_tech_field": row["target_tech_field"],
                "candidate_achievement_ids": candidates,
                "relevant_achievement_ids": [
                    aid for aid in candidates if grades.get(aid, 0) >= 1
                ],
                "relevance_grades": {aid: grades[aid] for aid in candidates if aid in grades},
                "annotator": row["annotator"],
                "notes": row["notes"],
                "dataset_version": VERSION,
            }
        )
    write_jsonl(EVAL_DIR / f"retrieval_queries_{VERSION}.jsonl", query_jsonl)

    write_csv(pair_path, pair_rows, PAIR_COLUMNS)
    pair_jsonl: list[dict] = []
    for row in pair_rows:
        item = {key: row[key] for key in PAIR_COLUMNS if key != "relevance_grade"}
        item["relevance_grade"] = int(row["relevance_grade"])
        item["dataset_version"] = VERSION
        pair_jsonl.append(item)
    write_jsonl(EVAL_DIR / f"pair_labels_{VERSION}.jsonl", pair_jsonl)

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# 评测集双标裁决记录（v0.1）",
        "",
        f"- 生成时间：{now}",
        "- 首标：黄欣悦；第二标注人：PM（用户本人）",
        "- 双标范围：4 条 query（q09—q12，80 个候选）+ 10 对 pair",
        "- 双标 kappa（裁决前）：query 线性 0.4653 / 二次 0.6321；"
        "pair 线性 0.4828 / 二次 0.5714",
        "",
        "## 分类与修正规则",
        "",
        "| 类别 | 条数 | 规则 | 最终分 |",
        "| --- | ---: | --- | ---: |",
    ]
    for category in ("Q1a", "Q1b", "Q2", "Q3", "P1", "P2", "P3"):
        count = category_counts.get(category, 0)
        if not count:
            continue
        finals = sorted(
            {int(row["final_grade"]) for row in raw if row["category"] == category}
        )
        lines.append(
            f"| {category} | {count} | {CATEGORY_RULES[category]} | "
            f"{'/'.join(map(str, finals))} |"
        )
    lines += [
        "",
        "## 裁决结果",
        "",
        f"- query：{sum(changes.values())} 条 0→1（"
        + "、".join(f"{qid} {count}" for qid, count in sorted(changes.items()))
        + "）；16 条第二标注人的 2 分维持 1；无 1→2。",
        "- pair：3 条分歧分别按 P1/P2/P3 裁决为 1/0/1，与首标一致；"
        "第二标注人的分数记入 `adjudication`。",
        f"- query 最终分布：{dict(sorted(query_dist.items()))}；"
        f"显式分数 {sum(query_dist.values())}，其余按 0。",
        f"- pair 最终分布：{dict(sorted(pair_dist.items()))}。",
        "",
        "## 逐条记录",
        "",
        "见 `data/manifests/eval_adjudication_v0.1.csv`（39 行，含首标/二标/"
        "类别/规则/最终分/双方理由）。",
        "",
        "## 已知限制",
        "",
        "- pair 双标只有 10 对，n<30，线性 kappa 0.483、二次 0.571，低于 0.6；"
        "但同分率 85%，3 条分歧已全部裁决并有记录。",
        "- query 线性 kappa 0.465、二次 0.632；线性低于 0.6、二次达到 0.6。"
        "差异主要是 16 条 1/2 边界，均按 Q1a/Q1b/Q3 规则维持 1。",
        "- 本次裁决偏严格：只有候选直接覆盖 query 的硬约束才给 2；"
        "这对评测是保守选择，避免高估匹配效果。",
    ]
    (MANIFEST_DIR / "eval_adjudication_v0.1.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )

    # 最终标注报告
    summary = [
        "# 评测标注最终报告（v0.1）",
        "",
        f"- 冻结时间：{now}",
        "- query：20 条；pair：50 对",
        f"- query 最终分数：{dict(sorted(query_dist.items()))}；"
        f"未标候选按 0（{400 - sum(query_dist.values())} 个）",
        f"- pair 最终分数：{dict(sorted(pair_dist.items()))}",
        "- 双标：query 线性 0.4653 / 二次 0.6321；"
        "pair 线性 0.4828 / 二次 0.5714",
        f"- 裁决：{sum(changes.values())} 条 query 0→1；3 条 pair 分歧按 P1/P2/P3 裁决；"
        "详见 `data/manifests/eval_adjudication_v0.1.md`",
        "",
        "## 文件",
        "",
        f"- `data/eval/retrieval_queries_v0.1.csv` "
        f"sha256=`{sha256(query_path)}`",
        f"- `data/eval/retrieval_queries_v0.1.jsonl` "
        f"sha256=`{sha256(EVAL_DIR / 'retrieval_queries_v0.1.jsonl')}`",
        f"- `data/eval/pair_labels_v0.1.csv` sha256=`{sha256(pair_path)}`",
        f"- `data/eval/pair_labels_v0.1.jsonl` "
        f"sha256=`{sha256(EVAL_DIR / 'pair_labels_v0.1.jsonl')}`",
        "",
        "## 结论",
        "",
        "- 正式评测集使用人工首标 + 双标裁决后的标签；LLM 预标仅作对照，"
        "不进入正式文件。",
        "- query 的人工 2 分集中在英文/宽口径 query；中文硬指标 query "
        "严格按“硬约束是否被直接覆盖”给分。",
        "- pair 零 2 分是候选集性质；不强行改 2。",
    ]
    (MANIFEST_DIR / "eval_annotation_summary_v0.1.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8", newline="\n"
    )

    # 冻结 dataset manifest
    manifest_path = MANIFEST_DIR / "dataset_v0.1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evaluation"] = {
        "retrieval_queries": 20,
        "pairs": 50,
        "annotation_status": "frozen",
        "annotation_method": (
            "human_first_pass + independent_double_label + category_adjudication"
        ),
        "double_labeled": "4 query + 10 pair",
        "kappa_query_linear": 0.465318,
        "kappa_query_quadratic": 0.6321,
        "kappa_pair_linear": 0.482759,
        "kappa_pair_quadratic": 0.5714,
        "adjudication": (
            "20 query 0->1; 16 user 2s kept 1; "
            "3 pair decisions resolved to first annotator"
        ),
        "adjudication_log": "data/manifests/eval_adjudication_v0.1.md",
        "frozen_at": now,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"裁决记录：{adjudication_csv}")
    print(f"最终报告：{MANIFEST_DIR / 'eval_annotation_summary_v0.1.md'}")
    print(f"已冻结：{manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="按差距口径分类裁决双标分歧并冻结评测集",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--adjudication",
        type=Path,
        default=_ROOT / "data" / "interim" / "s09_review" / "adjudication_39.csv",
    )
    parser.add_argument("--dry-run", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
