#!/usr/bin/env python3
"""检索评测：三组基线 B0—B2（B3 待匹配引擎就绪后补）。

严格依据：
  - data/spec/eval_spec_v0.1.md §4（指标）/ §5（基线对比）
  - data/spec/data_contract_v0.1.md（字段口径）

基线：
  - B0：BM25 / 关键词（纯文本，自实现 BM25；文本用原始 title_original + abstract_original，
    不依赖抽取阶段的画像）
  - B1：纯向量（query 向量 vs 成果向量余弦相似度）
  - B2：标签硬过滤 + 向量（先按任一 tech_field 过滤，再向量排序；过滤为空则返回空结果，不回退全量）
  - B2-primary：B2 的消融版本，仅按主 tech_field 过滤

指标：Recall@10、Precision@5、nDCG@10、MRR。
相关口径：relevance_grade 0/1/2，1 或 2 记为“相关”；nDCG 用 2^g-1 增益。

输入：
  data/eval/retrieval_queries_<version>.jsonl        （20 条 query，标注后含 relevant/grades）
  data/processed/embeddings_<version>.jsonl          （embed.py 产出，B1/B2；只接受 text_type=capability_profile 且 dim=1024）
  data/processed/achievements_labeled_<version>.jsonl（extract_labels.py 产出，B2 用 tech_field）
  data/processed/achievements_clean_<version>.jsonl  （B0 用原始标题+摘要）

输出：
  data/manifests/baseline_<version>.md          （基线指标报告）
  data/manifests/baseline_<version>_top10.csv   （逐 query / 基线的 Top-K 明细）
  data/interim/eval_query_vectors_<version>.jsonl（query 向量缓存）

用法：
  python scripts/data/evaluate.py --version v0.1-thin
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
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

from config import EVAL_DIR, INTERIM_DIR, MANIFEST_DIR, PROCESSED_DIR  # noqa: E402
from scripts.common.llm_client import DashScopeClient, LlmClientError, text_hash  # noqa: E402

SPRINT = "2026-11-22"
TAXONOMY_VERSION = "v0.1"
EMBEDDING_DIM = 1024
DEFAULT_TOP_K = 10
DEFAULT_EMBEDDING_MODEL_VERSION = "qwen3.7-text-embedding-flash-1024-v1"

# ---------------------------------------------------------------------------
# 基础工具（纯标准库）
# ---------------------------------------------------------------------------
def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
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


def _embedding_model_version() -> str:
    return os.getenv("EMBEDDING_MODEL_VERSION", DEFAULT_EMBEDDING_MODEL_VERSION)


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _query_vectors_path(version: str, explicit: str | None = None) -> Path:
    return Path(explicit) if explicit else INTERIM_DIR / f"eval_query_vectors_{version}.jsonl"


def _load_query_vectors(
    path: Path, queries: list[dict], model: str, dim: int
) -> list[list[float]]:
    rows = {str(r.get("query_id")): r for r in _load_jsonl(path)}
    vectors: list[list[float]] = []
    for q in queries:
        qid = str(q.get("query_id"))
        row = rows.get(qid)
        if row is None:
            raise ValueError(f"query 向量缓存缺少 {qid}")
        if row.get("model") and row["model"] != model:
            raise ValueError(f"{qid} 向量模型 {row['model']} != {model}")
        if int(row.get("dim", dim)) != dim:
            raise ValueError(f"{qid} 向量维度 {row.get('dim')} != {dim}")
        expected_hash = text_hash(q.get("query_text", ""))
        if row.get("text_hash") and row["text_hash"] != expected_hash:
            raise ValueError(f"{qid} 向量 text_hash 与 query 文本不一致")
        vec = row.get("vector")
        if not isinstance(vec, list) or len(vec) != dim:
            raise ValueError(f"{qid} 向量长度不是 {dim}")
        vectors.append(vec)
    return vectors


def _write_query_vectors(
    path: Path,
    queries: list[dict],
    vectors: list[list[float]],
    *,
    model: str,
    dim: int,
    version: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for q, vec in zip(queries, vectors):
            record = {
                "query_id": q.get("query_id"),
                "query_text": q.get("query_text", ""),
                "text_hash": text_hash(q.get("query_text", "")),
                "model": model,
                "dim": dim,
                "vector": vec,
                "dataset_version": version,
                "created_at": _now_utc(),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


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
    relevant_ids = _split(query.get("relevant_achievement_ids"))
    for aid in relevant_ids:
        graded.setdefault(aid, 1)
    return target_fields, candidates, graded


def _relevant_set(graded: dict[str, int]) -> set[str]:
    return {aid for aid, g in graded.items() if g > 0}


def _restrict_graded(graded: dict[str, int], candidates: list[str]) -> dict[str, int]:
    """把标注限定在候选集内，避免候选集外的标注影响 IDCG / Recall。"""
    if not candidates:
        return graded
    cand_set = set(candidates)
    return {aid: g for aid, g in graded.items() if aid in cand_set}


# ---------------------------------------------------------------------------
# 加载与排序（拆出便于测试）
# ---------------------------------------------------------------------------
def _load_ach_vectors(
    embeddings: list[dict], *, dim: int = EMBEDDING_DIM
) -> tuple[dict[str, list[float]], set[str]]:
    """从 embedding 记录加载成果向量，只接受 text_type=capability_profile 且 dim 一致。

    返回 (ach_vectors, models)。dim 不一致 / 向量长度不符 / 混模型抛 ValueError。
    """
    vectors: dict[str, list[float]] = {}
    models: set[str] = set()
    for e in embeddings:
        if e.get("object_type") != "achievement":
            continue
        if e.get("text_type") != "capability_profile":
            continue
        vec = e.get("vector")
        if not isinstance(vec, list):
            continue
        rec_dim = e.get("dim")
        if rec_dim is not None and int(rec_dim) != dim:
            raise ValueError(f"向量维度异常 {rec_dim}（期望 {dim}）：{e.get('object_id')}")
        if len(vec) != dim:
            raise ValueError(f"向量长度 {len(vec)} != {dim}：{e.get('object_id')}")
        vectors[e["object_id"]] = vec
        if e.get("model"):
            models.add(e["model"])
    if len(models) > 1:
        raise ValueError(f"成果向量混用多个模型：{sorted(models)}")
    return vectors, models


def _rank_b0(cand_ids: list[str], bm25: BM25, index_of: dict[str, int], qtext: str) -> list[str]:
    """B0：BM25 排序；不在索引里的候选跳过（不落到第 0 篇文档）。"""
    return sorted(
        (aid for aid in cand_ids if aid in index_of),
        key=lambda aid: bm25.score(qtext, index_of[aid]),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    queries_path = Path(args.queries) if args.queries else EVAL_DIR / f"retrieval_queries_{args.version}.jsonl"
    embeddings_path = Path(args.embeddings) if args.embeddings else PROCESSED_DIR / f"embeddings_{args.version}.jsonl"
    labels_path = Path(args.labels) if args.labels else PROCESSED_DIR / f"achievements_labeled_{args.version}.jsonl"
    achievements_path = Path(args.achievements) if args.achievements else PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    out_path = Path(args.output) if args.output else MANIFEST_DIR / f"baseline_{args.version}.md"
    top_k = int(getattr(args, "top_k", DEFAULT_TOP_K))
    if top_k < 0:
        print("[错误] --top-k 不能为负数。", file=sys.stderr)
        return 2
    details_path = (
        Path(args.details_out)
        if getattr(args, "details_out", None)
        else MANIFEST_DIR / f"baseline_{args.version}_top10.csv"
    )
    query_vectors_path = _query_vectors_path(
        args.version, getattr(args, "query_vectors", None)
    )

    # 缺失输入直接报错，避免静默产出部分基线。
    missing = [
        (name, path)
        for name, path in (
            ("query", queries_path),
            ("embeddings", embeddings_path),
            ("labels", labels_path),
            ("achievements", achievements_path),
        )
        if not path.exists()
    ]
    if missing:
        for name, path in missing:
            print(f"[错误] 找不到 {name} 文件：{path}", file=sys.stderr)
        return 2

    queries = _load_jsonl(queries_path)
    embeddings = _load_jsonl(embeddings_path)
    labels = _load_jsonl(labels_path)
    achievements = _load_jsonl(achievements_path)

    # 成果向量（校验 text_type / dim / 混模型）
    try:
        ach_vectors, ach_embedding_models = _load_ach_vectors(embeddings)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    # 成果 tech_field（B2 用：任一标签命中；B2-primary 只用主标签）
    ach_primary: dict[str, str] = {}
    ach_tech_fields: dict[str, set[str]] = {}
    label_by_id: dict[str, dict] = {}
    for rec in labels:
        aid = rec.get("achievement_id")
        if not aid:
            continue
        label_by_id[aid] = rec
        tech_fields = [t for t in rec.get("tags", []) if t.get("dimension") == "tech_field"]
        codes = {t["code"] for t in tech_fields if t.get("code")}
        if codes:
            ach_tech_fields[aid] = codes
        primary = next((t["code"] for t in tech_fields if t.get("is_primary")), None)
        if primary is None and tech_fields:
            primary = tech_fields[0]["code"]
        if primary:
            ach_primary[aid] = primary

    # 标注完整性：无标注 → 不产出基线（在调用 query embedding API 前检查）
    annotated = sum(1 for q in queries if _relevant_set(_parse_query(q)[2]))
    if annotated == 0:
        print("[错误] 评测集未标注，不产出基线（请先完成 20 query + 50 pair 标注）。", file=sys.stderr)
        return 2
    rc = 0 if annotated == len(queries) else 1
    if annotated < len(queries):
        print(f"[警告] 仅标注 {annotated}/{len(queries)} 条 query，基线指标为部分结果。", file=sys.stderr)

    # 成果原始文本（B0 用 title + abstract，不依赖抽取画像）
    achievements_by_id = {
        a.get("achievement_id"): a for a in achievements if a.get("achievement_id")
    }
    ach_texts: dict[str, str] = {}
    for a in achievements:
        aid = a.get("achievement_id")
        title = (a.get("title_original") or "").strip()
        abstract = (a.get("abstract_original") or a.get("abstract_truncated") or "").strip()
        text = " ".join(part for part in (title, abstract) if part)
        if aid and text:
            ach_texts[aid] = text

    # 全量成果 ID（画像文本与向量取并集，避免只用一边）
    all_ids = list(dict.fromkeys(list(ach_texts) + list(ach_vectors)))

    # B0 索引：只对「有原始文本」的成果建 BM25；未知候选不参与排序
    b0_ids = [aid for aid in all_ids if aid in ach_texts]
    bm25 = BM25([ach_texts[aid] for aid in b0_ids])
    index_of = {aid: i for i, aid in enumerate(b0_ids)}
    b0_missing = len(all_ids) - len(b0_ids)

    # query 向量：优先读冻结缓存；缺失时调用共享客户端生成并写回缓存。
    dim = EMBEDDING_DIM
    query_model = next(iter(ach_embedding_models), None)
    if query_vectors_path.exists():
        try:
            cached_rows = _load_jsonl(query_vectors_path)
            if not cached_rows:
                raise ValueError(f"query 向量缓存为空：{query_vectors_path}")
            query_model = query_model or str(cached_rows[0].get("model") or "")
            if not query_model:
                raise ValueError(f"query 向量缓存缺少 model：{query_vectors_path}")
            if ach_embedding_models and query_model not in ach_embedding_models:
                raise ValueError(
                    f"query 向量模型 {query_model} 与成果向量模型 {sorted(ach_embedding_models)} 不一致"
                )
            q_vectors = _load_query_vectors(query_vectors_path, queries, query_model, dim)
            query_vectors_source = "cache"
        except ValueError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 2
    else:
        try:
            client = DashScopeClient()
        except LlmClientError as exc:
            print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
            print("       也可提供 --query-vectors 指向已冻结的 query 向量缓存。", file=sys.stderr)
            return 2
        query_model = client.embedding_model
        if int(client.embedding_dim) != dim:
            print(f"[错误] embedding 维度 {client.embedding_dim} != {dim}，请检查 .env。", file=sys.stderr)
            return 2
        if ach_embedding_models and query_model not in ach_embedding_models:
            print(f"[错误] query 向量模型 {query_model} 与成果向量模型 {sorted(ach_embedding_models)} 不一致。", file=sys.stderr)
            return 2
        try:
            q_vectors = client.embed_texts(
                [q.get("query_text", "") for q in queries], text_type="query", dimensions=dim
            )
        except LlmClientError as exc:
            print(f"[错误] query 向量化失败：{exc}", file=sys.stderr)
            return 1
        if len(q_vectors) != len(queries):
            print(f"[错误] query 向量返回 {len(q_vectors)} 条，期望 {len(queries)} 条。", file=sys.stderr)
            return 1
        _write_query_vectors(
            query_vectors_path, queries, q_vectors,
            model=query_model, dim=dim, version=args.version,
        )
        query_vectors_source = "generated"

    baselines = ["B0", "B1", "B2", "B2-primary"]
    agg = {b: {"recall10": 0.0, "prec5": 0.0, "ndcg10": 0.0, "mrr": 0.0, "n": 0} for b in baselines}
    per_query_rows: list[str] = []
    top10_rows: list[dict] = []
    b2_empty_queries = 0
    b2_primary_empty_queries = 0
    candidate_ids_total: set[str] = set()
    candidate_missing: set[str] = set()
    candidate_missing_text: set[str] = set()
    candidate_missing_vector: set[str] = set()

    for qi, q in enumerate(queries):
        qid = q.get("query_id", "?")
        qtext = q.get("query_text", "")
        target_fields, candidates, graded = _parse_query(q)
        graded = _restrict_graded(graded, candidates)
        relevant = _relevant_set(graded)

        candidate_ids_total.update(candidates)
        for aid in candidates:
            if aid not in all_ids:
                candidate_missing.add(aid)
            if aid not in ach_texts:
                candidate_missing_text.add(aid)
            if aid not in ach_vectors:
                candidate_missing_vector.add(aid)

        cand_ids = candidates if candidates else all_ids

        for baseline in baselines:
            if baseline == "B0":
                ranked = _rank_b0(cand_ids, bm25, index_of, qtext)
                score_type = "bm25"
                filter_status = "text_indexed"

                def score(aid: str) -> float:
                    return bm25.score(qtext, index_of[aid])

            elif baseline == "B1":
                ranked = sorted(
                    (aid for aid in cand_ids if aid in ach_vectors),
                    key=lambda aid: (-_cosine(q_vectors[qi], ach_vectors[aid]), aid),
                )
                score_type = "cosine"
                filter_status = "vector_eligible"

                def score(aid: str) -> float:
                    return _cosine(q_vectors[qi], ach_vectors[aid])

            elif baseline == "B2":
                filtered = [
                    aid for aid in cand_ids
                    if ach_tech_fields.get(aid, set()) & target_fields
                ]
                if not filtered:
                    b2_empty_queries += 1
                ranked = sorted(
                    (aid for aid in filtered if aid in ach_vectors),
                    key=lambda aid: (-_cosine(q_vectors[qi], ach_vectors[aid]), aid),
                )
                score_type = "cosine"
                filter_status = "eligible"

                def score(aid: str) -> float:
                    return _cosine(q_vectors[qi], ach_vectors[aid])

            elif baseline == "B2-primary":
                filtered = [
                    aid for aid in cand_ids
                    if ach_primary.get(aid) in target_fields
                ]
                if not filtered:
                    b2_primary_empty_queries += 1
                ranked = sorted(
                    (aid for aid in filtered if aid in ach_vectors),
                    key=lambda aid: (-_cosine(q_vectors[qi], ach_vectors[aid]), aid),
                )
                score_type = "cosine"
                filter_status = "primary_eligible"

                def score(aid: str) -> float:
                    return _cosine(q_vectors[qi], ach_vectors[aid])

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

            if top_k:
                for rank, aid in enumerate(ranked[:top_k], 1):
                    label = label_by_id.get(aid, {})
                    extraction = label.get("extraction") or {}
                    top10_rows.append(
                        {
                            "query_id": qid,
                            "query_text": qtext,
                            "target_tech_field": ";".join(sorted(target_fields)),
                            "baseline": baseline,
                            "rank": rank,
                            "achievement_id": aid,
                            "title_original": (achievements_by_id.get(aid) or {}).get("title_original", ""),
                            "score": f"{score(aid):.6f}",
                            "score_type": score_type,
                            "relevance_grade": graded.get(aid, 0),
                            "relevant": str(graded.get(aid, 0) > 0).lower(),
                            "primary_tech_field": ach_primary.get(aid, ""),
                            "tech_fields": ";".join(sorted(ach_tech_fields.get(aid, set()))),
                            "review_status": label.get("review_status", ""),
                            "trl": "" if extraction.get("trl") is None else extraction.get("trl"),
                            "filter_status": filter_status,
                        }
                    )

    if top_k:
        details_path.parent.mkdir(parents=True, exist_ok=True)
        detail_fields = [
            "query_id", "query_text", "target_tech_field", "baseline", "rank",
            "achievement_id", "title_original", "score", "score_type",
            "relevance_grade", "relevant", "primary_tech_field", "tech_fields",
            "review_status", "trl", "filter_status",
        ]
        with details_path.open("w", encoding="utf-8", newline="\n") as fh:
            writer = csv.DictWriter(fh, fieldnames=detail_fields)
            writer.writeheader()
            writer.writerows(top10_rows)

    # 汇总
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

    embedding_model = next(iter(ach_embedding_models), query_model)
    input_hashes = {
        "queries": _sha256_file(queries_path),
        "embeddings": _sha256_file(embeddings_path),
        "labels": _sha256_file(labels_path),
        "achievements": _sha256_file(achievements_path),
        "query_vectors": _sha256_file(query_vectors_path),
    }
    report = "\n".join(
        [
            f"# 基线评测报告（{args.version}）",
            "",
            f"- 生成时间：{_now_utc()}",
            f"- git commit：{_git_commit() or '（未知）'}",
            f"- sprint：{SPRINT}",
            f"- embedding_model：{embedding_model}；dim：{EMBEDDING_DIM}；version：{_embedding_model_version()}",
            f"- taxonomy_version：{TAXONOMY_VERSION}；eval set：{args.version}",
            f"- query 数：{len(queries)}；已标注：{annotated}",
            f"- query 向量：{query_vectors_source}，`{_relpath(query_vectors_path)}`，"
            f"sha256 `{input_hashes['query_vectors']}`",
            f"- 成果向量数：{len(ach_vectors)}；B0 文本数：{len(ach_texts)}（缺 {b0_missing}）；"
            f"主标签数：{len(ach_primary)}；任一标签数：{len(ach_tech_fields)}",
            f"- 候选 ID：{len(candidate_ids_total)}（缺 clean 文本 {len(candidate_missing_text)}，"
            f"缺向量 {len(candidate_missing_vector)}，缺任一侧 {len(candidate_missing)}）",
            f"- Top-K 明细：`{_relpath(details_path)}`（K={top_k}）",
            "",
            "## 指标汇总（B0=BM25，B1=纯向量，B2=任一标签过滤+向量，B2-primary=仅主标签消融）",
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
            "- B2 使用任一 tech_field 命中；B2-primary 保留仅主标签消融。",
            "- B2 标签硬过滤为空时返回空结果（不回退全量）；本次空过滤 query 数："
            f"B2={b2_empty_queries}，B2-primary={b2_primary_empty_queries}。",
            f"- B0 用原始标题+摘要；缺文本的成果不计入 B0 排序（缺 {b0_missing} 条）。",
            "- 错误分析（假阳/假阴各 5 例）见 `data/manifests/error_analysis_v0.1.md`。",
            "",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\n报告已生成：{out_path}")
    print("\n".join(summary_lines))

    if b0_missing > 0:
        print(f"[警告] B0 文本覆盖不足：{b0_missing} 条成果缺原始标题/摘要。", file=sys.stderr)
        rc = 1 if rc == 0 else rc
    if candidate_missing_text or candidate_missing_vector:
        print(
            f"[警告] 候选覆盖不足：缺文本 {len(candidate_missing_text)}，"
            f"缺向量 {len(candidate_missing_vector)}。",
            file=sys.stderr,
        )
        rc = 1 if rc == 0 else rc
    return rc


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
    parser.add_argument("--achievements", default=None, help="清洗成果 jsonl（默认 data/processed/achievements_clean_<version>.jsonl，B0 用原始标题+摘要）")
    parser.add_argument("--query-vectors", default=None, help="冻结的 query 向量 jsonl；默认 data/interim/eval_query_vectors_<version>.jsonl")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Top-K 明细条数；0 表示不输出")
    parser.add_argument("--details-out", default=None, help="Top-K 明细 CSV（默认 data/manifests/baseline_<version>_top10.csv）")
    parser.add_argument("--output", default=None, help="报告输出（默认 data/manifests/baseline_<version>.md）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
