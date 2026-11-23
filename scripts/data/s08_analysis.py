#!/usr/bin/env python3
"""S-08 read-only quality/analysis pass for the accepted v0.1 data.

This script intentionally does not write to PostgreSQL and does not modify
data/processed. It reads the S-05-accepted v0.1 files and the frozen query
vectors, then produces:

  data/manifests/baseline_v0.1_s08_addendum.md
  data/manifests/baseline_v0.1_top10.csv
  data/manifests/error_analysis_v0.1.md / .csv
  data/manifests/needs_review_disposition_v0.1.csv
  data/manifests/proposed_data_corrections_v0.1.csv
  data/manifests/s08_analysis_summary_v0.1.json

B2-any is a supplementary sensitivity view. The official S-04 baseline
(B2-primary) is not rewritten; B2-primary is recomputed here only for
comparison with the same query-vector cache.
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

from config import EVAL_DIR, MANIFEST_DIR, PROCESSED_DIR  # noqa: E402
from scripts.common.llm_client import text_hash  # noqa: E402
from scripts.data.evaluate import (  # noqa: E402
    BM25,
    _cosine,
    _load_ach_vectors,
    _load_jsonl,
    _mrr,
    _ndcg_at_k,
    _parse_query,
    _precision_at_k,
    _rank_b0,
    _recall_at_k,
    _relevant_set,
    _restrict_graded,
)

DEFAULT_QUERY_VECTORS = _ROOT / "data" / "interim" / "s04_eval_query_vectors_v0.1.jsonl"
BASELINES = ("B0", "B1", "B2", "B2-primary")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _split(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip():
        return [v.strip() for v in value.split(";") if v.strip()]
    return []


def _metric_row(name: str, agg: dict, n: int) -> str:
    if n == 0:
        return f"| {name} | — | — | — | — | 0 |"
    return (
        f"| {name} | {agg['recall10']/n:.3f} | {agg['prec5']/n:.3f} "
        f"| {agg['ndcg10']/n:.3f} | {agg['mrr']/n:.3f} | {n} |"
    )


def _load_query_vectors(path: Path, queries: list[dict], dim: int = 1024) -> list[list[float]]:
    rows = {str(r.get("query_id")): r for r in _load_jsonl(path)}
    vectors: list[list[float]] = []
    for q in queries:
        qid = str(q.get("query_id"))
        row = rows.get(qid)
        if row is None:
            raise ValueError(f"query vector cache missing {qid}")
        if int(row.get("dim", dim)) != dim:
            raise ValueError(f"{qid}: dim {row.get('dim')} != {dim}")
        expected = text_hash(q.get("query_text", ""))
        if row.get("text_hash") and row["text_hash"] != expected:
            raise ValueError(f"{qid}: text_hash mismatch")
        vec = row.get("vector")
        if not isinstance(vec, list) or len(vec) != dim:
            raise ValueError(f"{qid}: vector is not {dim} floats")
        vectors.append(vec)
    return vectors


def _metric_agg() -> dict:
    return {"recall10": 0.0, "prec5": 0.0, "ndcg10": 0.0, "mrr": 0.0, "n": 0}


def _md_escape(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _select_error_cases(
    ranked_by_query: list[tuple[str, list[str], dict[str, int], list[float]]],
    titles: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    fps: list[dict] = []
    fns: list[dict] = []
    for qid, ranked, graded, scores in ranked_by_query:
        for rank, aid in enumerate(ranked[:10], 1):
            if graded.get(aid, 0) == 0 and len(fps) < 5:
                fps.append(
                    {
                        "type": "FP",
                        "query_id": qid,
                        "achievement_id": aid,
                        "title": titles.get(aid, ""),
                        "grade": 0,
                        "rank": rank,
                        "score": scores[rank - 1] if rank <= len(scores) else "",
                        "reason": "同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。",
                        "suggestion": "B3 增加材料体系/场景/证据检查，或将此类候选作为 hard negative。",
                    }
                )
        for aid, grade in graded.items():
            if grade > 0 and aid not in ranked[:10] and len(fns) < 5:
                rank = ranked.index(aid) + 1 if aid in ranked else ""
                fns.append(
                    {
                        "type": "FN",
                        "query_id": qid,
                        "achievement_id": aid,
                        "title": titles.get(aid, ""),
                        "grade": grade,
                        "rank": rank,
                        "score": "",
                        "reason": "人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。",
                        "suggestion": "B3 用摘要片段或系统级证据补足；保留人工 grade，不为了提高指标改标注。",
                    }
                )
        if len(fps) >= 5 and len(fns) >= 5:
            break
    return fps, fns


def run(args: argparse.Namespace) -> int:
    version = args.version
    queries_path = Path(args.queries) if args.queries else EVAL_DIR / f"retrieval_queries_{version}.jsonl"
    embeddings_path = Path(args.embeddings) if args.embeddings else PROCESSED_DIR / f"embeddings_{version}.jsonl"
    labels_path = Path(args.labels) if args.labels else PROCESSED_DIR / f"achievements_labeled_{version}.jsonl"
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{version}.jsonl"
    achievements_path = Path(args.achievements) if args.achievements else PROCESSED_DIR / f"achievements_clean_{version}.jsonl"
    query_vectors_path = Path(args.query_vectors) if args.query_vectors else DEFAULT_QUERY_VECTORS
    out_dir = Path(args.out_dir) if args.out_dir else MANIFEST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    for label, path in (
        ("queries", queries_path),
        ("embeddings", embeddings_path),
        ("labels", labels_path),
        ("profiles", profiles_path),
        ("achievements", achievements_path),
        ("query_vectors", query_vectors_path),
    ):
        if not path.exists():
            print(f"[错误] 缺少 {label}: {path}", file=sys.stderr)
            return 2

    queries = _load_jsonl(queries_path)
    embeddings = _load_jsonl(embeddings_path)
    labels = _load_jsonl(labels_path)
    profiles = _load_jsonl(profiles_path)
    achievements = _load_jsonl(achievements_path)
    query_vectors = _load_query_vectors(query_vectors_path, queries)

    ach_vectors, ach_models = _load_ach_vectors(embeddings)
    if len(ach_vectors) != 300:
        print(f"[错误] 成果向量 {len(ach_vectors)} != 300", file=sys.stderr)
        return 2

    label_by_id: dict[str, dict] = {}
    ach_primary: dict[str, str] = {}
    ach_fields: dict[str, set[str]] = {}
    for rec in labels:
        aid = rec.get("achievement_id")
        if not aid:
            continue
        label_by_id[aid] = rec
        tech = [t for t in (rec.get("tags") or []) if t.get("dimension") == "tech_field"]
        codes = {t.get("code") for t in tech if t.get("code")}
        if codes:
            ach_fields[aid] = codes
        primary = next((t.get("code") for t in tech if t.get("is_primary")), None)
        if primary is None and tech:
            primary = tech[0].get("code")
        if primary:
            ach_primary[aid] = primary

    titles: dict[str, str] = {}
    ach_texts: dict[str, str] = {}
    for a in achievements:
        aid = a.get("achievement_id")
        title = (a.get("title_original") or "").strip()
        abstract = (a.get("abstract_original") or a.get("abstract_truncated") or "").strip()
        text = " ".join(x for x in (title, abstract) if x)
        if aid:
            titles[aid] = title
            if text:
                ach_texts[aid] = text

    all_ids = list(dict.fromkeys(list(ach_texts) + list(ach_vectors)))
    b0_ids = [aid for aid in all_ids if aid in ach_texts]
    bm25 = BM25([ach_texts[aid] for aid in b0_ids])
    index_of = {aid: i for i, aid in enumerate(b0_ids)}

    agg = {b: _metric_agg() for b in BASELINES}
    top_rows: list[dict] = []
    b2_cases: list[tuple[str, list[str], dict[str, int], list[float]]] = []
    b2_empty = 0
    b2_primary_empty = 0

    for qi, q in enumerate(queries):
        qid = str(q.get("query_id"))
        qtext = q.get("query_text", "")
        target, candidates, graded = _parse_query(q)
        graded = _restrict_graded(graded, candidates)
        relevant = _relevant_set(graded)
        cand_ids = candidates or all_ids
        qvec = query_vectors[qi]

        ranked_by_baseline: dict[str, list[str]] = {}
        scores_by_baseline: dict[str, list[float]] = {}
        for baseline in BASELINES:
            if baseline == "B0":
                ranked = _rank_b0(cand_ids, bm25, index_of, qtext)
                scores = [bm25.score(qtext, index_of[aid]) for aid in ranked]
            else:
                if baseline == "B1":
                    eligible = [aid for aid in cand_ids if aid in ach_vectors]
                elif baseline == "B2":
                    eligible = [
                        aid for aid in cand_ids
                        if ach_fields.get(aid, set()) & target and aid in ach_vectors
                    ]
                    if not eligible:
                        b2_empty += 1
                else:
                    eligible = [
                        aid for aid in cand_ids
                        if ach_primary.get(aid) in target and aid in ach_vectors
                    ]
                    if not eligible:
                        b2_primary_empty += 1
                pairs = [(aid, _cosine(qvec, ach_vectors[aid])) for aid in eligible]
                pairs.sort(key=lambda x: (-x[1], x[0]))
                ranked = [aid for aid, _ in pairs]
                scores = [score for _, score in pairs]
            ranked_by_baseline[baseline] = ranked
            scores_by_baseline[baseline] = scores

            if relevant:
                r10 = _recall_at_k(ranked, relevant, 10)
                p5 = _precision_at_k(ranked, relevant, 5)
                n10 = _ndcg_at_k(ranked, graded, 10)
                mrr = _mrr(ranked, relevant)
                agg[baseline]["recall10"] += r10
                agg[baseline]["prec5"] += p5
                agg[baseline]["ndcg10"] += n10
                agg[baseline]["mrr"] += mrr
                agg[baseline]["n"] += 1
            else:
                r10 = p5 = n10 = mrr = 0.0

            for rank, aid in enumerate(ranked[: args.top_k], 1):
                rec = label_by_id.get(aid, {})
                ext = rec.get("extraction") or {}
                top_rows.append(
                    {
                        "query_id": qid,
                        "query_text": qtext,
                        "target_tech_field": ";".join(sorted(target)),
                        "baseline": baseline,
                        "rank": rank,
                        "achievement_id": aid,
                        "title_original": titles.get(aid, ""),
                        "score": f"{scores[rank - 1]:.6f}",
                        "relevance_grade": graded.get(aid, 0),
                        "relevant": str(graded.get(aid, 0) > 0).lower(),
                        "primary_tech_field": ach_primary.get(aid, ""),
                        "tech_fields": ";".join(sorted(ach_fields.get(aid, set()))),
                        "review_status": rec.get("review_status", ""),
                        "trl": "" if ext.get("trl") is None else ext.get("trl"),
                    }
                )

        b2_cases.append(
            (qid, ranked_by_baseline["B2"], graded, scores_by_baseline["B2"])
        )

    n = len(queries)
    addendum = "\n".join(
        [
            f"# S-08 v0.1 评测补充报告（{version}）",
            "",
            f"- 生成时间：{_now_utc()}",
            "- 性质：**只读补充分析**，不替代 S-04 的正式 baseline，不改数据库、不改 `data/processed/`。",
            f"- 输入 query：`{_rel(queries_path)}` sha256 `{_sha256(queries_path)}`",
            f"- 输入 labels：`{_rel(labels_path)}` sha256 `{_sha256(labels_path)}`",
            f"- 输入 embeddings：`{_rel(embeddings_path)}` sha256 `{_sha256(embeddings_path)}`",
            f"- 冻结 query 向量：`{_rel(query_vectors_path)}` sha256 `{_sha256(query_vectors_path)}`",
            "",
            "## 指标（同一套 20 query、同一冻结 query 向量）",
            "",
            "| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR | 有效 query 数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            _metric_row("B0", agg["B0"], n),
            _metric_row("B1", agg["B1"], n),
            _metric_row("B2（任一 tech_field）", agg["B2"], n),
            _metric_row("B2-primary（仅主标签）", agg["B2-primary"], n),
            "",
            "说明：B2-any 是 S-08 的补充敏感性口径；B2-primary 是 S-04 原有的正式口径，"
            "本报告重算仅为同一 query 向量下对照。B1 的 Precision@5 与 S-04 报告的 0.770 有差异，"
            "原因是本次使用冻结 query 向量；不修改 S-04 历史报告。",
            "",
            f"- B2 空过滤 query 数：{b2_empty}；B2-primary 空过滤 query 数：{b2_primary_empty}。",
            f"- 成果向量模型：{sorted(ach_models)}；向量数：{len(ach_vectors)}。",
            "",
            "## 明细",
            "",
            f"- Top-{args.top_k}：`{_rel(out_dir / f'baseline_{version}_top10.csv')}`",
            f"- 错误分析：`{_rel(out_dir / 'error_analysis_v0.1.md')}` / `.csv`",
            "",
            "## 边界",
            "",
            "- 本报告不修改 `data/eval/` 的冻结标注，不修改 S-04 的 `baseline_v0.1.md`。",
            "- 任何正式口径调整都必须由 PM 明确签收，并保留原 S-04 报告。",
        ]
    )
    (out_dir / f"baseline_{version}_s08_addendum.md").write_text(addendum, encoding="utf-8", newline="\n")

    top_fields = [
        "query_id", "query_text", "target_tech_field", "baseline", "rank",
        "achievement_id", "title_original", "score", "relevance_grade", "relevant",
        "primary_tech_field", "tech_fields", "review_status", "trl",
    ]
    with (out_dir / f"baseline_{version}_top10.csv").open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=top_fields)
        writer.writeheader()
        writer.writerows(top_rows)

    fps, fns = _select_error_cases(b2_cases, titles)
    error_rows = fps + fns
    error_fields = [
        "type", "query_id", "achievement_id", "title", "grade", "rank", "score",
        "reason", "suggestion",
    ]
    with (out_dir / "error_analysis_v0.1.csv").open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=error_fields)
        writer.writeheader()
        writer.writerows(error_rows)

    error_md = "\n".join(
        [
            "# v0.1 基线错误分析（B2-any 补充口径）",
            "",
            "> 对象：S-08 补充报告中的 B2（任一 `tech_field` 命中 + 向量）。",
            "> 5 假阳 + 5 假阴为自动选取的检查样本，理由为归因建议，不替代人工逐条复核。",
            "",
            "| 类型 | query | 成果 | grade | rank | 根因/建议 |",
            "| --- | --- | --- | ---: | ---: | --- |",
            *[
                f"| {r['type']} | `{r['query_id']}` | `{r['achievement_id']}` {_md_escape(r['title'])} "
                f"| {r['grade']} | {r['rank']} | {_md_escape(r['reason'])} |"
                for r in error_rows
            ],
            "",
            "- 这不是 S-04 正式 B2-primary 的错误分析；若 PM 将 B2-any 定为正式口径，"
            "应重新生成正式错误分析并保留本文件为敏感性分析。",
        ]
    )
    (out_dir / "error_analysis_v0.1.md").write_text(error_md, encoding="utf-8", newline="\n")

    profile_len = {
        p.get("achievement_id"): len(p.get("text", "")) for p in profiles if p.get("achievement_id")
    }
    ledger_rows: list[dict] = []
    for rec in labels:
        if rec.get("review_status") != "needs_review":
            continue
        aid = rec.get("achievement_id", "")
        ext = rec.get("extraction") or {}
        tags = rec.get("tags") or []
        tech = [t for t in tags if t.get("dimension") == "tech_field"]
        reasons: list[str] = []
        if profile_len.get(aid, 0) > 250:
            reasons.append("profile>250")
        if ext.get("trl") is None:
            reasons.append("trl=null")
        if not any(t.get("is_primary") for t in tech):
            reasons.append("no_primary_tech_field")
        bad_metrics = [
            m for m in (ext.get("key_metrics") or [])
            if not all((m.get(k) or "").strip() if isinstance(m.get(k), str) else m.get(k) is not None
                       for k in ("name", "value", "unit", "evidence"))
        ]
        if bad_metrics:
            reasons.append("key_metrics_invalid")
        if any(not (t.get("evidence") or "").strip() for t in tags):
            reasons.append("tag_no_evidence")
        if not reasons:
            reasons.append("llm_flagged_needs_review")
        ledger_rows.append(
            {
                "achievement_id": aid,
                "review_status": rec.get("review_status", ""),
                "profile_len": profile_len.get(aid, ""),
                "trl": "" if ext.get("trl") is None else ext.get("trl"),
                "tech_fields": ";".join(sorted({t.get("code") for t in tech if t.get("code")})),
                "reasons": ";".join(reasons),
                "decision": "keep_needs_review_no_db_change",
                "action": "S-08: retain current DB row; no reimport",
                "reembed_required": "false",
            }
        )
    ledger_rows.sort(key=lambda r: r["achievement_id"])
    ledger_fields = [
        "achievement_id", "review_status", "profile_len", "trl", "tech_fields",
        "reasons", "decision", "action", "reembed_required",
    ]
    with (out_dir / "needs_review_disposition_v0.1.csv").open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=ledger_fields)
        writer.writeheader()
        writer.writerows(ledger_rows)

    proposed: list[dict] = []
    for rec in labels:
        aid = rec.get("achievement_id", "")
        ext = rec.get("extraction") or {}
        if rec.get("review_status") == "pending" and ext.get("trl") is None:
            proposed.append(
                {
                    "achievement_id": aid,
                    "proposal": "review_status pending -> needs_review",
                    "reason": "TRL=null with no evidence",
                    "applied": "false",
                    "requires_versioning": "true",
                    "note": "tag/extraction tables have no dataset_version; use v0.1.1 + fresh DB if accepted",
                }
            )
    for rec in labels:
        if rec.get("achievement_id") == "ach_openalex_W4401101842":
            proposed.append(
                {
                    "achievement_id": "ach_openalex_W4401101842",
                    "proposal": "add tech_field=electrolyte (primary)",
                    "reason": "title says lithium-ion solid electrolytes of oxidates; current tags=[]",
                    "applied": "false",
                    "requires_versioning": "true",
                    "note": "would change 1268 tags / 299 primary; requires v0.1.1 + fresh DB",
                }
            )
            break
    proposed.sort(key=lambda r: (r["proposal"], r["achievement_id"]))
    proposed_fields = ["achievement_id", "proposal", "reason", "applied", "requires_versioning", "note"]
    with (out_dir / "proposed_data_corrections_v0.1.csv").open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=proposed_fields)
        writer.writeheader()
        writer.writerows(proposed)

    summary = {
        "generated_at": _now_utc(),
        "dataset_version": version,
        "read_only": True,
        "db_writes": 0,
        "queries": len(queries),
        "achievement_vectors": len(ach_vectors),
        "metrics": {
            b: {
                "recall10": round(agg[b]["recall10"] / n, 6),
                "precision5": round(agg[b]["prec5"] / n, 6),
                "ndcg10": round(agg[b]["ndcg10"] / n, 6),
                "mrr": round(agg[b]["mrr"] / n, 6),
            }
            for b in BASELINES
        },
        "top_rows": len(top_rows),
        "error_cases": {"fp": len(fps), "fn": len(fns)},
        "needs_review_rows": len(ledger_rows),
        "proposed_corrections": len(proposed),
        "query_vectors_sha256": _sha256(query_vectors_path),
        "inputs": {
            "queries": _sha256(queries_path),
            "labels": _sha256(labels_path),
            "embeddings": _sha256(embeddings_path),
            "profiles": _sha256(profiles_path),
            "achievements": _sha256(achievements_path),
        },
    }
    (out_dir / "s08_analysis_summary_v0.1.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S-08 read-only quality analysis")
    parser.add_argument("--version", default="v0.1")
    parser.add_argument("--queries", default=None)
    parser.add_argument("--embeddings", default=None)
    parser.add_argument("--labels", default=None)
    parser.add_argument("--profiles", default=None)
    parser.add_argument("--achievements", default=None)
    parser.add_argument("--query-vectors", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
