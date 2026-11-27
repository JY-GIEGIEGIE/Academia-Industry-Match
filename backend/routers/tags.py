
# ============================================================
# 成果与企业需求标签查询 API（S-11 / BE1）
#
# 功能说明：
# 1. 查询科研成果和企业技术需求的标签
# 2. 返回标签维度、编码、置信度、证据及审核状态
# 3. 保留模型、Prompt 版本和标签创建时间
# 4. 标签数据直接来自数据库，不生成或修改标签
# 5. 记录不存在时返回 404
# 6. 使用统一 API v0.1.2 响应格式
#
# 数据来源：achievement、achievement_tag、
#           demand、demand_tag
# 接口：
#   GET /api/v1/achievements/{achievement_id}/tags
#   GET /api/v1/demands/{demand_id}/tags
#
# 关联任务：S-11
# ============================================================

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import get_db


router = APIRouter(
    prefix="/api/v1",
    tags=["Tags"],
)


# ---------- Response models ----------

class TagItem(BaseModel):
    tag_id: str
    dimension: str
    code: str
    is_primary: bool
    confidence: float
    evidence: str | None = None
    method: str
    model: str | None = None
    prompt_version: str | None = None
    review_status: str
    created_at: datetime


class AchievementTagsData(BaseModel):
    achievement_id: str
    tags: list[TagItem] = Field(default_factory=list)


class DemandTagsData(BaseModel):
    demand_id: str
    tags: list[TagItem] = Field(default_factory=list)


class AchievementTagsResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: AchievementTagsData


class DemandTagsResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: DemandTagsData


# ---------- Shared database query ----------

def get_tags(
    db: Session,
    object_type: Literal["achievement", "demand"],
    object_id: str,
):
    # 表名和字段名只允许来自固定映射，避免 SQL 注入。
    tables = {
        "achievement": (
            "achievement",
            "achievement_tag",
            "achievement_id",
        ),
        "demand": (
            "demand",
            "demand_tag",
            "demand_id",
        ),
    }

    parent_table, tag_table, id_column = tables[object_type]

    # 先确认记录存在，再获取标签。
    # 存在但没有标签时应返回空数组，而不是 404。
    exists = db.execute(
        text(f"""
            SELECT 1
            FROM {parent_table}
            WHERE {id_column} = :object_id
        """),
        {"object_id": object_id},
    ).first()

    if exists is None:
        raise HTTPException(
            status_code=404,
            detail=f"{object_type.capitalize()} not found",
        )

    rows = db.execute(
        text(f"""
            SELECT
                tag_id,
                dimension,
                code,
                is_primary,
                confidence,
                evidence,
                method,
                model,
                prompt_version,
                review_status,
                created_at
            FROM {tag_table}
            WHERE {id_column} = :object_id
            ORDER BY dimension, is_primary DESC, code
        """),
        {"object_id": object_id},
    ).mappings().all()

    return [dict(row) for row in rows]


# ---------- Achievement tags ----------

@router.get(
    "/achievements/{achievement_id}/tags",
    response_model=AchievementTagsResponse,
    summary="Get achievement tags",
)
def get_achievement_tags(
    achievement_id: str,
    db: Session = Depends(get_db),
):
    tags = get_tags(
        db=db,
        object_type="achievement",
        object_id=achievement_id,
    )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "achievement_id": achievement_id,
            "tags": tags,
        },
    }


# ---------- Demand tags ----------

@router.get(
    "/demands/{demand_id}/tags",
    response_model=DemandTagsResponse,
    summary="Get demand tags",
)
def get_demand_tags(
    demand_id: str,
    db: Session = Depends(get_db),
):
    tags = get_tags(
        db=db,
        object_type="demand",
        object_id=demand_id,
    )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "demand_id": demand_id,
            "tags": tags,
        },
    }
