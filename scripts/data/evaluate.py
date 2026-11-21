#!/usr/bin/env python3
"""检索评测：三组基线 B0—B2（B3 待匹配引擎就绪后补）。

严格依据：
  - data/spec/eval_spec_v0.1.md §4（指标）/ §5（基线对比）
  - data/spec/data_contract_v0.1.md（字段口径）

基线：
  - B0：BM25 / 关键词（纯文本，自实现 BM25，无第三方依赖）
  - B1：纯向量（query 向量 vs 成果向量余弦相似度）
  - B2：标签硬过滤 + 向量（先按 tech_field 过滤，再向量排序）

指标：Recall@10、Precision@5、nDCG@10、MRR。
相关口径：relevance_grade 0/1/2，1 或 2 记为“相关”；nDCG 用 2^g-1 增益。

输入：
  data/eval/retrieval_queries_<version>.jsonl   （20 条 query，标注后含 relevant/grades）
  data/processed/embeddings_<version>.jsonl     （embed.py 产出，B1/B2）
  data/processed/achievements_labeled_<version>.jsonl （extract_labels.py 产出，B2 用 tech_field）
  data/processed/capability_profiles_<version>.jsonl  （B0 用中文画像作检索文本）

输出：
  data/manifests/baseline_<version>.md          （基线指标报告）

用法：
  python scripts/data/evaluate.py --version v0.1-thin
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
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
from scripts.common.llm_client import DashScopeClient, LlmClientError  # noqa: E402

# ---------------------------------------------------------------------------
# 基础工具（纯标准库）
# ---------------------------------------------------------------------------
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# BM25（自实现，处理中英混合：英文按词、中文按相邻双字）
# ---------------------------------------------------------------------------
_CJK = re.compile(r"[一-鿿]")


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = []
    for m in re.finditer(r"[a-z0-9]+", text):
        tokens.append(m.group())
    cjk_chars = _CJK.findall(text)
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])
    return tokens


class BM25:
    """极简 Okapi BM25，仅标准库。"""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens = [_tokenize(t) for t in corpus]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.n_docs = len(self.doc_tokens)
        self.avgdl = sum(self.doc_len) / self.n_docs if self.n_docs else 1.0
        self.doc_counts: list[Counter] = []
        self.doc_freq: dict[str, int] = {}
        for toks in self.doc_tokens:
            cnt = Counter(toks)
            self.doc_counts.append(cnt)
            for term in cnt:
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        self.idf = {
            term: math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for term, df in self.doc_freq.items()
        }

    def score(self, query: str, doc_index: int) -> float:
        q_terms = _tokenize(query)
        cnt = self.doc_counts[doc_index]
        dl = self.doc_len[doc_index] or 1
        norm = 1 - self.b + self.b * dl / self.avgdl
        score = 0.0
        for term in q_terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = cnt.get(term, 0)
            if tf == 0:
                continue
            score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * norm)
        return score


# ---------------------------------------------------------------------------
# 评测指标
# ---------------------------------------------------------------------------
def _precision_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant) / k


def _recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def _mrr(ranked_ids: list[str], relevant: set[str]) -> float:
    for i, aid in enumerate(ranked_ids, 1):
        if aid in relevant:
            return 1.0 / i
    return 0.0


def _ndcg_at_k(ranked_ids: list[str], graded: dict[str, int], k: int) -> float:
    def _gain(g: int) -> float:
        return (2 ** g - 1) if g > 0 else 0.0

    ideal = sorted(graded.values(), reverse=True)[:k]
    idcg = sum(_gain(g) / math.log2(i + 2) for i, g in enumerate(ideal))
    if idcg == 0.0:
        return 0.0
    dcg = 0.0
    for i, aid in enumerate(ranked_ids[:k]):
        g = graded.get(aid, 0)
        if g > 0:
            dcg += _gain(g) / math.log2(i + 2)
    return dcg / idcg


# ---------------------------------------------------------------------------
# 字段解析
# ---------------------------------------------------------------------------
def _split(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip():
        return [v.strip() for v in value.split(";") if v.strip()]
    return []


def _parse_query(query: dict) -> tuple[set[str], list[str], dict[str, int]]:
    """返回 (target_fields, candidates, graded)。graded 为 id->0/1/2。"""
    target_fields = set(_split(query.get("target_tech_field")))
    candidates = _split(query.get("candidate_achievement_ids"))

    graded: dict[str, int] = {}
    # 优先解析 relevance_grades："id:2;id:1"
    grades_raw = query.get("relevance_grades")
    if isinstance(grades_raw, str) and grades_raw.strip():
        for seg in grades_raw.split(";"):
            seg = seg.strip()
            if ":" in seg:
                aid, _, g = seg.partition(":")
                try:
                    graded[aid.strip()] = int(g.strip())
                except ValueError:
                    continue
    elif isinstance(grades_raw, dict):
        for aid, g in grades_raw.items():
            try:
                graded[str(aid)] = int(g)
            except (ValueError, TypeError):
                continue
    # 回退：只有 relevant_achievement_ids 时，相关按 grade=1 处理。
    relevant_ids = _split(query.get("relevant_achievement_ids"))
    for aid in relevant_ids:
        graded.setdefault(aid, 1)
    return target_fields, candidates, graded


def _relevant_set(graded: dict[str, int]) -> set[str]:
    return {aid for aid, g in graded.items() if g > 0}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    queries_path = Path(args.queries) if args.queries else EVAL_DIR / f"retrieval_queries_{args.version}.jsonl"
    embeddings_path = Path(args.embeddings) if args.embeddings else PROCESSED_DIR / f"embeddings_{args.version}.jsonl"
    labels_path = Path(args.labels) if args.labels else PROCESSED_DIR / f"achievements_labeled_{args.version}.jsonl"
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{args.version}.jsonl"
    out_path = Path(args.output) if args.output else MANIFEST_DIR / f"baseline_{args.version}.md"

    if not queries_path.exists():
        print(f"[错误] 找不到 query 文件：{queries_path}", file=sys.stderr)
        return 2

    queries = _load_jsonl(queries_path)
    embeddings = _load_jsonl(embeddings_path)
    labels = _load_jsonl(labels_path)
    profiles = _load_jsonl(profiles_path)

    print(f"query：{len(queries)} 条；向量：{len(embeddings)} 条；标签：{len(labels)} 条；画像：{len(profiles)} 条")

    # 成果向量：只取 object_type=achievement
    ach_vectors: dict[str, list[float]] = {
        e["object_id"]: e["vector"]
        for e in embeddings
        if e.get("object_type") == "achievement" and isinstance(e.get("vector"), list)
    }
    # 成果主 tech_field（B2 用）
    ach_primary: dict[str, str] = {}
    for rec in labels:
        aid = rec.get("achievement_id")
        if not aid:
            continue
        tech_fields = [t for t in rec.get("tags", []) if t.get("dimension") == "tech_field"]
        primary = next((t["code"] for t in tech_fields if t.get("is_primary")), None)
        if primary is None and tech_fields:
            primary = tech_fields[0]["code"]
        if primary:
            ach_primary[aid] = primary
    # 成果检索文本（B0 用中文画像）
    ach_texts: dict[str, str] = {
        p["achievement_id"]: (p.get("text") or "")
        for p in profiles
        if p.get("achievement_id") and p.get("text")
    }

    # 全量成果 ID 顺序（BM25 索引 & 兜底候选）
    all_ids = list(ach_texts) or list(ach_vectors)
    bm25 = BM25([ach_texts.get(aid, "") for aid in all_ids])
    index_of = {aid: i for i, aid in enumerate(all_ids)}

    # query 向量（API text_type=query）
    q_vectors: list[list[float]] = []
    if queries:
        try:
            client = DashScopeClient()
            q_vectors = client.embed_texts(
                [q.get("query_text", "") for q in queries], text_type="query"
            )
        except LlmClientError as exc:
            print(f"[警告] query 向量化失败，B1/B2 将跳过：{exc}", file=sys.stderr)

    baselines = ["B0", "B1", "B2"]
    # per-baseline 聚合：{metric: sum}
    agg = {b: {"recall10": 0.0, "prec5": 0.0, "ndcg10": 0.0, "mrr": 0.0, "n": 0} for b in baselines}
    per_query_rows: list[str] = []

    for qi, q in enumerate(queries):
        qid = q.get("query_id", "?")
        qtext = q.get("query_text", "")
        target_fields, candidates, graded = _parse_query(q)
        relevant = _relevant_set(graded)

        # 候选集：优先用 query 自带 candidate_achievement_ids，否则全量
        cand_ids = candidates if candidates else all_ids

        for baseline in baselines:
            if baseline == "B0":
                ranked = sorted(cand_ids, key=lambda aid: bm25.score(qtext, index_of.get(aid, 0)), reverse=True)
            elif baseline == "B1":
                if not q_vectors:
                    continue
                qvec = q_vectors[qi]
                ranked = sorted(
                    (aid for aid in cand_ids if aid in ach_vectors),
                    key=lambda aid: _cosine(qvec, ach_vectors[aid]),
                    reverse=True,
                )
            elif baseline == "B2":
                if not q_vectors:
                    continue
                qvec = q_vectors[qi]
                # 标签硬过滤：主 tech_field 命中目标字段
                filtered = [aid for aid in cand_ids if aid in ach_primary and ach_primary[aid] in target_fields]
                pool = filtered if filtered else cand_ids  # 过滤为空则回退，避免除零
                ranked = sorted(
                    (aid for aid in pool if aid in ach_vectors),
                    key=lambda aid: _cosine(qvec, ach_vectors[aid]),
                    reverse=True,
                )
            else:
                continue

            if relevant:
                r10 = _recall_at_k(ranked, relevant, 10)
                p5 = _precision_at_k(ranked, relevant, 5)
                n10 = _ndcg_at_k(ranked, graded, 10)
                m = _mrr(ranked, relevant)
                agg[baseline]["recall10"] += r10
                agg[baseline]["prec5"] += p5
                agg[baseline]["ndcg10"] += n10
                agg[baseline]["mrr"] += m
                agg[baseline]["n"] += 1
            else:
                m = r10 = p5 = n10 = 0.0

            per_query_rows.append(
                f"| {qid} | {baseline} | {r10:.3f} | {p5:.3f} | {n10:.3f} | {m:.3f} |"
            )

    # 汇总表
    summary_lines = [
        "| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR | 有效 query 数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for b in baselines:
        n = agg[b]["n"]
        if n == 0:
            summary_lines.append(f"| {b} | — | — | — | — | 0 |")
            continue
        summary_lines.append(
            f"| {b} | {agg[b]['recall10']/n:.3f} | {agg[b]['prec5']/n:.3f} "
            f"| {agg[b]['ndcg10']/n:.3f} | {agg[b]['mrr']/n:.3f} | {n} |"
        )

    annotated = sum(1 for q in queries if _relevant_set(_parse_query(q)[2]))
    report = "\n".join(
        [
            f"# 基线评测报告（{args.version}）",
            "",
            f"- 生成时间：{_now_utc()}",
            f"- git commit：{_git_commit() or '（未知）'}",
            f"- query 数：{len(queries)}；已标注：{annotated}",
            f"- 成果向量数：{len(ach_vectors)}；画像数：{len(ach_texts)}；主标签数：{len(ach_primary)}",
            "",
            "## 指标汇总（B0=BM25，B1=纯向量，B2=标签+向量）",
            "",
            *summary_lines,
            "",
            "## 逐 query 明细",
            "",
            "| query | 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
            *per_query_rows,
            "",
            "## 说明",
            "",
            "- B3（标签+向量+LLM 精排）待匹配引擎就绪后补。",
            "- 相关口径：relevance_grade 1/2 记为相关；nDCG 增益 2^g-1。",
            "- 错误分析（假阳/假阴各 5 例）在标注完成后人工补充。",
            "",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\n报告已生成：{out_path}")
    print("\n".join(summary_lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="检索评测：B0—B2 三组基线（B3 待匹配引擎）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1-thin", help="数据版本，决定各输入/输出文件名")
    parser.add_argument("--queries", default=None, help="query jsonl（默认 data/eval/retrieval_queries_<version>.jsonl）")
    parser.add_argument("--embeddings", default=None, help="向量 jsonl（默认 data/processed/embeddings_<version>.jsonl）")
    parser.add_argument("--labels", default=None, help="标签 jsonl（默认 data/processed/achievements_labeled_<version>.jsonl）")
    parser.add_argument("--profiles", default=None, help="画像 jsonl（默认 data/processed/capability_profiles_<version>.jsonl）")
    parser.add_argument("--output", default=None, help="报告输出（默认 data/manifests/baseline_<version>.md）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
