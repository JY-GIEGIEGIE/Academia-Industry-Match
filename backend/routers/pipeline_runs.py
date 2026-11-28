# ============================================================
# 匹配任务状态查询 API
#
# 功能说明：
# 1. 根据 run_id 查询异步匹配任务的执行状态
# 2. 返回任务 ID、阶段、状态、开始时间及结束时间
# 3. 支持 running、success、partial、failed 四种状态
# 4. 通过 JWT 认证限制未登录用户访问
# 5. 不向前端暴露内部错误日志及任务配置信息
# 6. 使用统一 API v0.1.2 响应格式
#
# 数据来源：pipeline_run
# 接口：
#   GET /api/v1/pipeline-runs/{run_id}
# ============================================================

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.services.match_dispatch import submit_matching_job

router = APIRouter(
    prefix="/api/v1/pipeline-runs",
    tags=["Pipeline Runs"],
)


class PipelineRunData(BaseModel):
    run_id: str
    stage: str
    status: Literal["running", "success", "partial", "failed"]
    started_at: datetime | None
    finished_at: datetime | None


class PipelineRunResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PipelineRunData

class PipelineRetryData(BaseModel):
    run_id: str
    dispatch_status: str


class PipelineRetryResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: PipelineRetryData

@router.get(
    "/{run_id}",
    response_model=PipelineRunResponse,
)
def get_pipeline_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    row = db.execute(
        text("""
            SELECT
                run_id,
                stage,
                status,
                started_at,
                finished_at
            FROM pipeline_run
            WHERE run_id = :run_id
        """),
        {"run_id": run_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Pipeline run not found",
        )

    return {
        "code": 0,
        "message": "success",
        "data": dict(row),
    }


@router.post(
    "/{run_id}/retry",
    response_model=PipelineRetryResponse,
    status_code=202,
    summary="Retry failed matching task submission",
)
def retry_pipeline_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # 1. 查询持久化投递记录。
    row = db.execute(
        text("""
            SELECT
                run_id,
                object_type,
                object_id,
                publisher_user_id,
                dispatch_status
            FROM match_dispatch
            WHERE run_id = :run_id
        """),
        {"run_id": run_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Matching dispatch job not found",
        )

    # 2. 只允许原发布者重试。
    if row["publisher_user_id"] != user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Only the original publisher can retry matching",
        )

    expected_role = (
        "researcher"
        if row["object_type"] == "achievement"
        else "enterprise"
    )

    if user["role"] != expected_role:
        raise HTTPException(
            status_code=403,
            detail="Invalid user role for matching retry",
        )

    # 3. 校验发布归属仍然有效。
    if row["object_type"] == "achievement":
        table = "achievement"
        id_column = "achievement_id"
    elif row["object_type"] == "demand":
        table = "demand"
        id_column = "demand_id"
    else:
        raise HTTPException(
            status_code=409,
            detail="Invalid matching job type",
        )

    owner = db.execute(
        text(f"""
            SELECT publisher_user_id
            FROM {table}
            WHERE {id_column} = :object_id
        """),
        {"object_id": row["object_id"]},
    ).scalar_one_or_none()

    if owner != user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="Publication ownership does not match",
        )

    # 4. 已进入 worker 的任务不能再直接入队。
    existing_run = db.execute(
        text("""
            SELECT status
            FROM pipeline_run
            WHERE run_id = :run_id
        """),
        {"run_id": run_id},
    ).scalar_one_or_none()

    if existing_run is not None:
        raise HTTPException(
            status_code=409,
            detail="Matching task already started",
        )

    # 5. 只有可恢复的投递状态允许重试。
    if row["dispatch_status"] != "retryable":
        raise HTTPException(
            status_code=409,
            detail="Matching job is not retryable",
        )

    # 6. 原子认领并复用 run_id 投递。
    submit_matching_job(db, run_id)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "run_id": run_id,
            "dispatch_status": "submitted",
        },
    }
