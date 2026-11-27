# ============================================================
# 成果与企业需求匹配结果查询 API
#
# 功能说明：
# 1. 根据企业需求查询推荐科研成果
# 2. 根据科研成果查询适配企业需求
# 3. 根据 match_id 查询完整匹配详情
# 4. 支持分页、最低匹配分数和失效状态筛选
# 5. 聚合成果与需求摘要，供前端直接展示
# 6. 详情返回风险、证据、模型及数据版本信息
# 7. 保留 B2 回退结果中的空 risk / evidence
#
# 数据来源：match_score、achievement、demand、
#           enterprise、achievement_tag、
#           achievement_text、achievement_extraction
#
# 接口：
#   GET /api/v1/demands/{demand_id}/matches
#   GET /api/v1/achievements/{achievement_id}/matches
#   GET /api/v1/matches/{match_id}
# ============================================================

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.database import get_db

from backend.routers.achievements import (
    AchievementSummary,
    FROM_SQL as ACHIEVEMENT_FROM_SQL,
    SELECT_SQL as ACHIEVEMENT_SELECT_SQL,
    to_achievement,
)

from backend.routers.demands import (
    DemandSummary,
    FROM_SQL as DEMAND_FROM_SQL,
    SELECT_SQL as DEMAND_SELECT_SQL,
    to_demand,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Matching Results"],
)


# ---------- Response models ----------

class MatchItem(BaseModel):
    match_id: str
    total_score: float
    tag_score: float
    semantic_score: float
    llm_score: float | None = None
    reason: str
    achievement_summary: AchievementSummary
    demand_summary: DemandSummary
    is_stale: bool
    created_at: datetime


class MatchDetail(MatchItem):
    risk: dict[str, Any] | None
    evidence: dict[str, Any] | None
    model: str
    prompt_version: str
    dataset_version: str
    taxonomy_version: str
    embedding_model_version: str


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class MatchListData(BaseModel):
    items: list[MatchItem]
    pagination: Pagination


class MatchListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: MatchListData


class MatchDetailResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: MatchDetail


# ---------- Matching fields ----------

MATCH_FIELDS = """
    m.match_id,
    m.achievement_id,
    m.demand_id,
    m.total_score,
    m.tag_score,
    m.semantic_score,
    m.llm_score,
    m.reason,
    m.risk,
    m.evidence,
    m.model,
    m.prompt_version,
    m.dataset_version,
    m.taxonomy_version,
    m.embedding_model_version,
    m.is_stale,
    m.created_at
"""


# ---------- Load related summaries in batches ----------

def get_achievement_summaries(db: Session, ids: list[str]):
    if not ids:
        return {}

    query = text(f"""
        {ACHIEVEMENT_SELECT_SQL}
        {ACHIEVEMENT_FROM_SQL}
        WHERE a.achievement_id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    rows = db.execute(
        query,
        {"ids": list(set(ids))},
    ).mappings().all()

    return {
        row["achievement_id"]: to_achievement(row)
        for row in rows
    }


def get_demand_summaries(db: Session, ids: list[str]):
    if not ids:
        return {}

    query = text(f"""
        {DEMAND_SELECT_SQL}
        {DEMAND_FROM_SQL}
        WHERE d.demand_id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    rows = db.execute(
        query,
        {"ids": list(set(ids))},
    ).mappings().all()

    return {
        row["demand_id"]: to_demand(row)
        for row in rows
    }


def build_matches(db: Session, rows, detail=False):
    achievements = get_achievement_summaries(
        db,
        [row["achievement_id"] for row in rows],
    )

    demands = get_demand_summaries(
        db,
        [row["demand_id"] for row in rows],
    )

    results = []

    for row in rows:
        item = dict(row)

        achievement_id = item.pop("achievement_id")
        demand_id = item.pop("demand_id")

        if achievement_id not in achievements:
            raise HTTPException(
                status_code=500,
                detail="Matching achievement is missing",
            )

        if demand_id not in demands:
            raise HTTPException(
                status_code=500,
                detail="Matching demand is missing",
            )

        item["achievement_summary"] = achievements[
            achievement_id
        ]
        item["demand_summary"] = demands[demand_id]

        if not detail:
            for key in (
                "risk",
                "evidence",
                "model",
                "prompt_version",
                "dataset_version",
                "taxonomy_version",
                "embedding_model_version",
            ):
                item.pop(key, None)

        results.append(item)

    return results


# ---------- Shared list query ----------

def list_matches(
    db: Session,
    object_type: Literal["achievement", "demand"],
    object_id: str,
    page: int,
    page_size: int,
    min_score: float,
    is_stale: bool,
):
    # 表名与字段名只能来自内部固定映射。
    definitions = {
        "achievement": ("achievement", "achievement_id"),
        "demand": ("demand", "demand_id"),
    }

    table, id_column = definitions[object_type]

    exists = db.execute(
        text(f"""
            SELECT 1
            FROM {table}
            WHERE {id_column} = :object_id
        """),
        {"object_id": object_id},
    ).first()

    if exists is None:
        raise HTTPException(
            status_code=404,
            detail=f"{object_type.capitalize()} not found",
        )

    conditions = f"""
        m.{id_column} = :object_id
        AND m.total_score >= :min_score
        AND m.is_stale = :is_stale
    """

    params = {
        "object_id": object_id,
        "min_score": min_score,
        "is_stale": is_stale,
    }

    total = db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM match_score AS m
            WHERE {conditions}
        """),
        params,
    ).scalar_one()

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    rows = db.execute(
        text(f"""
            SELECT {MATCH_FIELDS}
            FROM match_score AS m
            WHERE {conditions}
            ORDER BY m.total_score DESC, m.match_id
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": build_matches(db, rows),
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (
                    (total + page_size - 1) // page_size
                ),
            },
        },
    }


# ---------- GET matches by demand ----------

@router.get(
    "/demands/{demand_id}/matches",
    response_model=MatchListResponse,
    summary="Get recommended achievements for a demand",
)
def get_demand_matches(
    demand_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    min_score: float = Query(default=0, ge=0, le=100),
    is_stale: bool = False,
    db: Session = Depends(get_db),
):
    return list_matches(
        db=db,
        object_type="demand",
        object_id=demand_id,
        page=page,
        page_size=page_size,
        min_score=min_score,
        is_stale=is_stale,
    )


# ---------- GET matches by achievement ----------

@router.get(
    "/achievements/{achievement_id}/matches",
    response_model=MatchListResponse,
    summary="Get recommended demands for an achievement",
)
def get_achievement_matches(
    achievement_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    min_score: float = Query(default=0, ge=0, le=100),
    is_stale: bool = False,
    db: Session = Depends(get_db),
):
    return list_matches(
        db=db,
        object_type="achievement",
        object_id=achievement_id,
        page=page,
        page_size=page_size,
        min_score=min_score,
        is_stale=is_stale,
    )


# ---------- GET one complete match ----------

@router.get(
    "/matches/{match_id}",
    response_model=MatchDetailResponse,
    summary="Get matching result details",
)
def get_match(
    match_id: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(f"""
            SELECT {MATCH_FIELDS}
            FROM match_score AS m
            WHERE m.match_id = :match_id
        """),
        {"match_id": match_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Match not found",
        )

    return {
        "code": 0,
        "message": "success",
        "data": build_matches(db, [row], detail=True)[0],
    }
