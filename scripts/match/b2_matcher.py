#!/usr/bin/env python3
"""B2 匹配：标签硬过滤 + 向量余弦归一化（S-10，第二轮冲刺）。

依据：
  - data/spec/data_contract_v0.1.md §4.10（match_score 字段）
  - docs/02-需求分析/数据API契约_v0.1.md §6.4（risk/evidence 结构）
  - docs/09-项目管理/第二轮冲刺任务分配_2026-11-25.md（S-10）

做什么：
  1. 读取 v0.1.2 的标签、画像、向量、需求。
  2. 严格硬过滤：成果的 primary tech_field 必须命中需求 tech_fields，否则 pass。
  3. 对通过过滤的 pair 算余弦相似度，归一化到 0—100 分。
  4. match_id = f"match_{demand_id}_{achievement_id}"（同一 pair 两端唯一）。
  5. 生成规则化 reason；risk / evidence 置为 null，model / prompt_version 写 B2 来源标识
     （B2 未精排，见 API 契约 §6.4）。

不修改 v0.1.2 processed 数据，只读并产出新的匹配结果。

输入（data/processed/，均可 --xxx 覆盖）：
  achievements_labeled_<version>.jsonl   成果标签（primary tech_field）
  demands_<version>.jsonl                需求（tech_fields 等）
  capability_profiles_<version>.jsonl    成果中文画像（reason 用）
  embeddings_<version>.jsonl             成果 + 需求向量

输出：
  data/processed/matches_b2_<version>.jsonl
  data/manifests/match_b2_<version>.json

用法：
  python scripts/match/b2_matcher.py --version v0.1.2
  python scripts/match/b2_matcher.py --version v0.1.2 --top-k 10   # 每条需求保留 Top-10
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = _ROOT / "scripts" / "data"
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import MANIFEST_DIR, PROCESSED_DIR  # noqa: E402

SPRINT = "2026-11-29"
TAXONOMY_VERSION = "v0.1"
EMBEDDING_MODEL_VERSION = "qwen3.7-text-embedding-flash-1024-v1"
# B2 未调用 LLM；仍写非空的来源标识，满足 match_score.model/prompt_version 契约。
B2_MODEL = "b2"
B2_PROMPT_VERSION = "b2-rule-v1"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT.resolve()))
    except ValueError:
        return str(path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
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


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def normalize_cosine(cos: float) -> float:
    """余弦（约定 [0,1]）→ 0—100 分。"""
    return round(max(0.0, min(1.0, cos)) * 100.0, 2)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_achievement_primary(labels_path: Path) -> dict[str, dict]:
    """成果 primary tech_field（含置信度）。"""
    primary: dict[str, dict] = {}
    for rec in _read_jsonl(labels_path):
        aid = rec.get("achievement_id")
        if not aid:
            continue
        techs = [t for t in rec.get("tags", []) if t.get("dimension") == "tech_field"]
        if not techs:
            continue
        main = next((t for t in techs if t.get("is_primary")), None)
        if main is None or not main.get("code"):
            continue
        primary[aid] = {"code": main.get("code"), "confidence": main.get("confidence")}
    return primary


def load_vectors(
    embeddings_path: Path,
    object_type: str,
    text_type: str,
    *,
    expected_dim: int = 1024,
    expected_model: str | None = "qwen3.7-text-embedding-flash",
) -> dict[str, list[float]]:
    vecs: dict[str, list[float]] = {}
    for e in _read_jsonl(embeddings_path):
        if e.get("object_type") != object_type:
            continue
        if e.get("text_type") != text_type:
            continue
        if expected_model is not None and e.get("model") != expected_model:
            continue
        vec = e.get("vector")
        if not isinstance(vec, list) or len(vec) != expected_dim:
            continue
        if e.get("dim") is not None and int(e.get("dim")) != expected_dim:
            continue
        vecs[e.get("object_id")] = vec
    return vecs


def _rule_reason(primary: str, cos: float, score: float, ach_trl, demand_trl) -> str:
    parts = [f"技术领域匹配（{primary}）", f"语义相似度 {score:.1f}/100"]
    if ach_trl is not None and demand_trl is not None:
        if ach_trl < demand_trl:
            parts.append(f"成果 TRL {ach_trl} 低于需求要求 TRL {demand_trl}")
        else:
            parts.append(f"成果 TRL {ach_trl} 满足需求要求 TRL {demand_trl}")
    return "；".join(parts)


# ---------------------------------------------------------------------------
# 匹配核心（供 CLI 与后续 Celery 任务复用）
# ---------------------------------------------------------------------------
def match_demand(
    demand: dict,
    achievement_ids: list[str],
    ach_primary: dict[str, dict],
    ach_vectors: dict[str, list[float]],
    ach_trl: dict[str, int | None],
    demand_vector: list[float] | None,
    *,
    dataset_version: str,
    top_k: int | None = None,
) -> list[dict]:
    """对一条需求匹配全量成果，返回按分数降序的 match 列表。"""
    if demand_vector is None:
        return []
    demand_fields = set(demand.get("tech_fields") or [])
    matches: list[dict] = []
    for aid in achievement_ids:
        primary = ach_primary.get(aid)
        if not primary or primary.get("code") not in demand_fields:
            continue  # 硬过滤：tech_field 对不上直接 pass
        a_vec = ach_vectors.get(aid)
        if a_vec is None:
            continue
        cos = cosine(demand_vector, a_vec)
        score = normalize_cosine(cos)
        reason = _rule_reason(primary["code"], cos, score, ach_trl.get(aid), demand.get("required_trl"))
        rec = {
            "match_id": f"match_{demand['demand_id']}_{aid}",
            "demand_id": demand["demand_id"],
            "achievement_id": aid,
            "total_score": score,
            "tag_score": 100.0,
            "semantic_score": score,
            "llm_score": None,
            "reason": reason,
            "risk": None,
            "evidence": None,
            "model": B2_MODEL,
            "prompt_version": B2_PROMPT_VERSION,
            "dataset_version": dataset_version,
            "taxonomy_version": TAXONOMY_VERSION,
            "embedding_model_version": EMBEDDING_MODEL_VERSION,
            "is_stale": False,
            "created_at": _now_utc(),
        }
        matches.append(rec)
    matches.sort(key=lambda m: m["total_score"], reverse=True)
    if top_k is not None and top_k > 0:
        matches = matches[:top_k]
    return matches


def load_achievement_trl(labels_path: Path) -> dict[str, int | None]:
    trl: dict[str, int | None] = {}
    for rec in _read_jsonl(labels_path):
        aid = rec.get("achievement_id")
        ext = rec.get("extraction") or {}
        trl[aid] = ext.get("trl")
    return trl


def run(args: argparse.Namespace) -> int:
    labels_path = Path(args.labels) if args.labels else PROCESSED_DIR / f"achievements_labeled_{args.version}.jsonl"
    demands_path = Path(args.demands) if args.demands else PROCESSED_DIR / f"demands_{args.version}.jsonl"
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{args.version}.jsonl"
    embeddings_path = Path(args.embeddings) if args.embeddings else PROCESSED_DIR / f"embeddings_{args.version}.jsonl"
    out_path = Path(args.output) if args.output else PROCESSED_DIR / f"matches_b2_{args.version}.jsonl"

    for name, path in (("labels", labels_path), ("demands", demands_path),
                       ("profiles", profiles_path), ("embeddings", embeddings_path)):
        if not path.exists():
            print(f"[错误] 找不到 {name} 文件：{path}", file=sys.stderr)
            return 2

    ach_primary = load_achievement_primary(labels_path)
    ach_trl = load_achievement_trl(labels_path)
    ach_vectors = load_vectors(embeddings_path, "achievement", "capability_profile")
    demand_vectors = load_vectors(embeddings_path, "demand", "need_profile")
    demands = _read_jsonl(demands_path)
    profiles = _read_jsonl(profiles_path)

    achievement_ids = list(ach_primary)
    print(f"成果 {len(achievement_ids)} 条（有向量 {len(ach_vectors)}）；需求 {len(demands)} 条（有向量 {len(demand_vectors)}）")

    all_matches: list[dict] = []
    no_vector_demands = 0
    for demand in demands:
        matches = match_demand(
            demand, achievement_ids, ach_primary, ach_vectors, ach_trl,
            demand_vectors.get(demand.get("demand_id")),
            dataset_version=args.version, top_k=args.top_k,
        )
        if demand.get("demand_id") not in demand_vectors:
            no_vector_demands += 1
        all_matches.extend(matches)

    # 全局按 match_id 去重（同一 pair 只一条），再按需求+分数排。
    deduped = {m["match_id"]: m for m in all_matches}.values()
    all_matches = sorted(deduped, key=lambda m: (m["demand_id"], -m["total_score"]))

    _write_jsonl(out_path, all_matches)

    manifest = {
        "sprint": SPRINT,
        "task": "S-10",
        "stage": "match",
        "status": "success",
        "dataset_version": args.version,
        "taxonomy_version": TAXONOMY_VERSION,
        "embedding_model_version": EMBEDDING_MODEL_VERSION,
        "b2_model": B2_MODEL,
        "b2_prompt_version": B2_PROMPT_VERSION,
        "match_id_rule": "match_{demand_id}_{achievement_id}",
        "hard_filter": "achievement primary tech_field in demand tech_fields",
        "labels_path": _relpath(labels_path),
        "demands_path": _relpath(demands_path),
        "profiles_path": _relpath(profiles_path),
        "embeddings_path": _relpath(embeddings_path),
        "output_path": _relpath(out_path),
        "input_achievements": len(achievement_ids),
        "input_demands": len(demands),
        "profiles_count": len(profiles),
        "achievements_with_vector": len(ach_vectors),
        "demands_without_vector": no_vector_demands,
        "output_matches": len(all_matches),
        "git_commit": _git_commit(),
        "args": vars(args),
    }
    manifest_path = MANIFEST_DIR / f"match_b2_{args.version}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n匹配结果：{len(all_matches)} 条（去重后）")
    print(f"输出：{out_path}")
    print(f"清单：{manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="B2 匹配：标签硬过滤 + 向量余弦归一化（0—100）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1.2", help="数据版本，决定输入/输出文件名")
    parser.add_argument("--labels", default=None, help="标签 jsonl（默认 data/processed/achievements_labeled_<version>.jsonl）")
    parser.add_argument("--demands", default=None, help="需求 jsonl（默认 data/processed/demands_<version>.jsonl）")
    parser.add_argument("--profiles", default=None, help="画像 jsonl（默认 data/processed/capability_profiles_<version>.jsonl）")
    parser.add_argument("--embeddings", default=None, help="向量 jsonl（默认 data/processed/embeddings_<version>.jsonl）")
    parser.add_argument("--output", default=None, help="输出 jsonl（默认 data/processed/matches_b2_<version>.jsonl）")
    parser.add_argument("--top-k", type=int, default=None, help="每条需求保留 Top-K（默认全部）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
