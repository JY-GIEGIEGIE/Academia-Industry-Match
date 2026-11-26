#!/usr/bin/env python3
"""Celery 匹配任务（S-10）：B2 匹配 + P1 精排，幂等写 match_score，状态写 pipeline_run。

幂等：任务一开始连本地测试库（DATABASE_URL）查 match_score，match_id 已存在则跳过插入；
      插入再叠加 ON CONFLICT (match_id) DO NOTHING 兜底，防止重复执行写脏数据。
状态：pipeline_run.status 启动写 running，结束写 success（P1 全部成功）或 partial（P1 失败回退 B2）。

依赖迁移 0003（match_score.risk/evidence 可空）；B2 阶段 risk/evidence 为 NULL，
model/prompt_version 写 b2 / b2-rule-v1，P1 成功后覆盖为真实精排模型与 Prompt 版本。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# 让 `backend.tasks` 无论从哪个 cwd 导入，都能找到 config / scripts.match / scripts.common。
_ROOT = Path(__file__).resolve().parents[1]
_DATA_SCRIPT_DIR = _ROOT / "scripts" / "data"
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.worker import celery_app  # noqa: E402
from config import PROCESSED_DIR  # noqa: E402
from scripts.match import b2_matcher, p1_rerank  # noqa: E402
from scripts.common.llm_client import DashScopeClient  # noqa: E402

DATASET_VERSION = "v0.1.2"
P1_TOP_K = int(os.getenv("P1_TOP_K", "10"))


class MatchObjectNotFound(LookupError):
    """发布对象不在 v0.1.2 匹配输入中；不能静默 success 0。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dsn() -> str:
    # 第二轮演示库：由 S-12 在 docker-compose 里把 DATABASE_URL 指向开发演示库 s2_mvp_20261125。
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL 未设置；匹配任务必须显式指向 s2_mvp_* 开发库")
    database = urlparse(dsn).path.lstrip("/")
    if not database.startswith("s2_mvp_"):
        raise RuntimeError(f"DATABASE_URL 必须指向 s2_mvp_* 开发库，当前数据库：{database or '<unknown>'}")
    return dsn


def _connect():
    import psycopg  # 延迟导入，避免 worker 启动时强依赖

    return psycopg.connect(_dsn(), connect_timeout=5)


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


# ---------------------------------------------------------------------------
# DB：状态与幂等
# ---------------------------------------------------------------------------
def _set_status(
    run_id: str,
    status: str,
    *,
    input_count: int = 0,
    output_count: int = 0,
    finished_at: datetime | None = None,
    config: dict | None = None,
) -> None:
    """写/更新 pipeline_run（stage=match）；running 时 finished_at 为 NULL。"""
    config_json = json.dumps(config or {}, ensure_ascii=False)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_run
                (run_id, stage, started_at, finished_at, status, input_count, output_count, config, dataset_version)
            VALUES
                (%s, 'match', %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (run_id) DO UPDATE
                SET status = EXCLUDED.status,
                    finished_at = EXCLUDED.finished_at,
                    input_count = EXCLUDED.input_count,
                    output_count = EXCLUDED.output_count,
                    config = EXCLUDED.config
            """,
            (
                run_id,
                _now(),
                finished_at,
                status,
                input_count,
                output_count,
                config_json,
                DATASET_VERSION,
            ),
        )


def _existing_match_ids(conn, match_ids: list[str]) -> set[str]:
    if not match_ids:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT match_id FROM match_score WHERE match_id = ANY(%s)", (match_ids,))
        return {row[0] for row in cur.fetchall()}


def _insert_match(conn, m: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO match_score
                (match_id, achievement_id, demand_id, total_score, tag_score,
                 semantic_score, llm_score, reason, risk, evidence, model,
                 prompt_version, dataset_version, taxonomy_version,
                 embedding_model_version, is_stale, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id) DO NOTHING
            """,
            (
                m["match_id"], m["achievement_id"], m["demand_id"], m["total_score"],
                m["tag_score"], m["semantic_score"], m.get("llm_score"), m["reason"],
                json.dumps(m.get("risk"), ensure_ascii=False) if m.get("risk") is not None else None,
                json.dumps(m.get("evidence"), ensure_ascii=False) if m.get("evidence") is not None else None,
                m.get("model"), m.get("prompt_version"), m.get("dataset_version"),
                m.get("taxonomy_version"), m.get("embedding_model_version"),
                m.get("is_stale", False), m.get("created_at", _now()),
            ),
        )


# ---------------------------------------------------------------------------
# B2 + P1 编排
# ---------------------------------------------------------------------------
def _compute_b2_matches(object_type: str, object_id: str, version: str) -> list[dict]:
    labels_path = PROCESSED_DIR / f"achievements_labeled_{version}.jsonl"
    demands_path = PROCESSED_DIR / f"demands_{version}.jsonl"
    embeddings_path = PROCESSED_DIR / f"embeddings_{version}.jsonl"

    ach_primary = b2_matcher.load_achievement_primary(labels_path)
    ach_trl = b2_matcher.load_achievement_trl(labels_path)
    ach_vectors = b2_matcher.load_vectors(embeddings_path, "achievement", "capability_profile")
    demand_vectors = b2_matcher.load_vectors(embeddings_path, "demand", "need_profile")
    demands = _read_jsonl(demands_path)

    if object_type == "demand":
        demand = next((d for d in demands if d.get("demand_id") == object_id), None)
        if demand is None:
            raise MatchObjectNotFound(f"需求不存在于 {version} 匹配输入：{object_id}")
        if object_id not in demand_vectors:
            raise MatchObjectNotFound(f"需求缺少 {version} 向量：{object_id}")
        return b2_matcher.match_demand(
            demand, list(ach_primary), ach_primary, ach_vectors, ach_trl,
            demand_vectors.get(object_id), dataset_version=version,
        )

    if object_id not in ach_primary:
        raise MatchObjectNotFound(f"成果不存在于 {version} 匹配输入：{object_id}")
    if object_id not in ach_vectors:
        raise MatchObjectNotFound(f"成果缺少 {version} 向量：{object_id}")

    # achievement：与全量需求逐一匹配
    matches: list[dict] = []
    for demand in demands:
        matches.extend(
            b2_matcher.match_demand(
                demand, [object_id], ach_primary, ach_vectors, ach_trl,
                demand_vectors.get(demand.get("demand_id")), dataset_version=version,
            )
        )
    return matches


def _p1_rerank(matches: list[dict], version: str, top_k: int = P1_TOP_K) -> bool:
    """仅对新增候选的 Top-K 做 P1；返回是否发生失败（True=有回退 B2）。"""
    if not matches:
        return False
    try:
        demands = {d.get("demand_id"): d for d in _read_jsonl(PROCESSED_DIR / f"demands_{version}.jsonl")}
        labels = {r.get("achievement_id"): r for r in _read_jsonl(PROCESSED_DIR / f"achievements_labeled_{version}.jsonl")}
        profiles = {p.get("achievement_id"): p for p in _read_jsonl(PROCESSED_DIR / f"capability_profiles_{version}.jsonl")}
        achievements = {a.get("achievement_id"): a for a in _read_jsonl(PROCESSED_DIR / f"achievements_clean_{version}.jsonl")}
        client = DashScopeClient()
        model = client.chat_model
    except Exception as exc:  # noqa: BLE001 —— 无法加载上下文/初始化客户端 → 整体 P1 回退
        print(f"[P1] 初始化失败，整体回退 B2：{exc}", file=sys.stderr)
        return True

    ranked = sorted(
        enumerate(matches),
        key=lambda item: (-float(item[1].get("total_score") or 0), item[1].get("match_id") or ""),
    )
    selected_indexes = {index for index, _ in ranked[: max(0, top_k)]}

    p1_failed = False
    for i, m in enumerate(matches):
        if i not in selected_indexes:
            continue
        demand = demands.get(m.get("demand_id"))
        ach_label = labels.get(m.get("achievement_id"))
        if demand is None or ach_label is None:
            p1_failed = True
            continue
        dctx = p1_rerank._demand_context(demand)
        actx = p1_rerank._achievement_context(
            ach_label,
            profiles.get(m.get("achievement_id")),
            achievements.get(m.get("achievement_id")),
        )
        matches[i], ok = p1_rerank.rerank_one(
            client, m, dctx, actx, model=model, prompt_version=p1_rerank.PROMPT_VERSION
        )
        if not ok:
            p1_failed = True
    return p1_failed


def _run_match(object_type: str, object_id: str, run_id: str | None, version: str) -> dict:
    run_id = run_id or f"match-{object_type}-{object_id}-{_now():%Y%m%d%H%M%S}"
    _set_status(run_id, "running", config={"object_type": object_type, "object_id": object_id, "version": version})
    try:
        matches = _compute_b2_matches(object_type, object_id, version)
        match_ids = [m["match_id"] for m in matches]
        with _connect() as conn:
            existing = _existing_match_ids(conn, match_ids)
        new_matches = [m for m in matches if m["match_id"] not in existing]

        # 先查已有 match_id，再只对新增候选做 P1，避免重复 LLM 调用。
        p1_failed = _p1_rerank(new_matches, version)

        inserted = 0
        with _connect() as conn:
            for m in new_matches:
                _insert_match(conn, m)
                inserted += 1

        status = "partial" if p1_failed else "success"
        _set_status(
            run_id,
            status,
            input_count=len(matches),
            output_count=inserted,
            finished_at=_now(),
            config={"object_type": object_type, "object_id": object_id, "version": version},
        )
        return {
            "run_id": run_id,
            "status": status,
            "input": len(matches),
            "inserted": inserted,
            "skipped": len(existing),
        }
    except Exception:
        _set_status(run_id, "failed", finished_at=_now())
        raise


@celery_app.task(bind=True, name="backend.tasks.run_match_for_achievement")
def run_match_for_achievement(self, achievement_id: str, run_id: str | None = None, version: str = DATASET_VERSION):
    """对一条成果与全量异侧需求做 B2 + P1，幂等写 match_score。"""
    return _run_match("achievement", achievement_id, run_id, version)


@celery_app.task(bind=True, name="backend.tasks.run_match_for_demand")
def run_match_for_demand(self, demand_id: str, run_id: str | None = None, version: str = DATASET_VERSION):
    """对一条需求与全量异侧成果做 B2 + P1，幂等写 match_score。"""
    return _run_match("demand", demand_id, run_id, version)
