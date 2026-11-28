# ============================================================
# S-11 匹配任务持久化投递与失败恢复
#
# 功能：
# 1. 原子认领待投递任务，避免并发提交
# 2. 通过 Celery 投递成果/需求匹配任务
# 3. 入队成功后记录 submitted
# 4. 入队失败后记录 retryable
# 5. 重试时复用原有 run_id
#
# 注意：
# Broker 确认丢失时可能存在不确定投递状态。
# Worker 端仍需实现 run_id 幂等执行保护。
# ============================================================

import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CELERY_RETRY_POLICY = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 1,
    "interval_max": 3,
}

# 超过该时长的 submitting 视为进程中断，可由 retry 重新认领。
STALE_SUBMITTING_SECONDS = 300


def submit_matching_job(db: Session, run_id: str):
    """
    投递 pending/retryable 任务。
    并发请求只能成功认领一次。
    """

    # 1. 原子认领任务。
    try:
        row = db.execute(
            text("""
                UPDATE match_dispatch
                SET dispatch_status = 'submitting',
                    attempt_count = attempt_count + 1,
                    claimed_at = now(),
                    updated_at = now(),
                    last_error = NULL
                WHERE run_id = :run_id
                  AND (
                      dispatch_status IN ('pending', 'retryable')
                      OR (
                          dispatch_status = 'submitting'
                          AND claimed_at < now() - make_interval(secs => :stale_seconds)
                      )
                  )
                RETURNING object_type, object_id
            """),
            {
                "run_id": run_id,
                "stale_seconds": STALE_SUBMITTING_SECONDS,
            },
        ).mappings().first()

        db.commit()

    except Exception:
        db.rollback()
        raise

    if row is None:
        raise HTTPException(
            status_code=409,
            detail="Matching job is not available for submission",
        )

    object_type = row["object_type"]
    object_id = row["object_id"]

    # 2. 根据发布对象选择 S-10 Celery 任务。
    from backend.tasks import (
        run_match_for_achievement,
        run_match_for_demand,
    )

    if object_type == "achievement":
        task = run_match_for_achievement
    elif object_type == "demand":
        task = run_match_for_demand
    else:
        raise RuntimeError("Unsupported dispatch object type")

    # 3. 向 Redis / Celery 发送任务。
    try:
        task.apply_async(
            args=[object_id, run_id],
            task_id=run_id,
            retry=True,
            retry_policy=CELERY_RETRY_POLICY,
        )

    except Exception:
        logger.exception(
            "Matching task submission failed: run_id=%s",
            run_id,
        )

        # 4. 保留失败记录供发布者后续重试。
        db.execute(
            text("""
                UPDATE match_dispatch
                SET dispatch_status = 'retryable',
                    last_error = 'Celery broker submission failed',
                    updated_at = now()
                WHERE run_id = :run_id
                  AND dispatch_status = 'submitting'
            """),
            {"run_id": run_id},
        )
        db.commit()

        raise HTTPException(
            status_code=503,
            detail=(
                "Publication saved, but matching enqueue failed; "
                "the job can be retried"
            ),
        )

    # 5. Broker 已接受投递。
    db.execute(
        text("""
            UPDATE match_dispatch
            SET dispatch_status = 'submitted',
                submitted_at = now(),
                updated_at = now()
            WHERE run_id = :run_id
              AND dispatch_status = 'submitting'
        """),
        {"run_id": run_id},
    )
    db.commit()

    return run_id
