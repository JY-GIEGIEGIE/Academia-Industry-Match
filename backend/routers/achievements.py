
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import get_current_user, security
from backend.database import get_db


router = APIRouter(
    prefix="/api/v1/achievements",
    tags=["Achievements"],
)


# ---------- Response models ----------

class TechField(BaseModel):
    code: str
    is_primary: bool


class AchievementSummary(BaseModel):
    achievement_id: str
    title_original: str
    abstract_preview: str | None = None
    capability_profile_zh: str | None = None
    publication_year: int
    type: str
    source: str
    source_url: str
    language: str
    trl: int | None = None
    tech_fields: list[TechField] = Field(default_factory=list)
    application_scenarios: list[str] = Field(default_factory=list)
    is_simulated: bool
    dataset_version: str

    # Sprint 2 publication fields
    publisher_user_id: str | None = None
    published_at: datetime | None = None


class AchievementDetail(AchievementSummary):
    doi: str | None = None
    abstract_original: str
    venue: str | None = None
    keywords: list[Any] = Field(default_factory=list)
    topics: list[Any] = Field(default_factory=list)
    clean_status: str
    review_status: str
    trl_evidence: str | None = None
    key_metrics: list[Any] = Field(default_factory=list)
    material_system: str | None = None
    process: list[Any] = Field(default_factory=list)
    ip_status: str | None = None


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class AchievementListData(BaseModel):
    items: list[AchievementSummary]
    pagination: Pagination


class AchievementListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: AchievementListData


class AchievementDetailResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: AchievementDetail


# ---------- Database queries ----------

# Latest extraction per achievement.
# TRL must remain NULL when evidence is unavailable.

FROM_SQL = """
FROM achievement AS a

LEFT JOIN LATERAL (
    SELECT
        ae.trl,
        ae.trl_evidence,
        ae.key_metrics,
        ae.material_system,
        ae.process,
        ae.ip_status
    FROM achievement_extraction AS ae
    WHERE ae.achievement_id = a.achievement_id
    ORDER BY ae.created_at DESC, ae.extraction_id DESC
    LIMIT 1
) AS ext ON TRUE

LEFT JOIN LATERAL (
    SELECT atx.text
    FROM achievement_text AS atx
    WHERE atx.achievement_id = a.achievement_id
      AND atx.text_type = 'capability_profile_zh'
    ORDER BY atx.created_at DESC, atx.text_id DESC
    LIMIT 1
) AS profile ON TRUE
"""


SELECT_SQL = """
SELECT
    a.achievement_id,
    a.title_original,
    a.abstract_original,
    profile.text AS capability_profile_zh,
    a.publication_year,
    a.type,
    a.source,
    a.source_url,
    a.language,
    ext.trl,
    a.is_simulated,
    a.dataset_version,
    a.publisher_user_id,
    a.published_at,

    a.doi,
    a.venue,
    a.keywords,
    a.topics,
    a.clean_status,
    a.review_status,

    ext.trl_evidence,
    ext.key_metrics,
    ext.material_system,
    ext.process,
    ext.ip_status,

    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'code', tag.code,
                    'is_primary', tag.is_primary
                )
                ORDER BY tag.is_primary DESC, tag.code
            )
            FROM achievement_tag AS tag
            WHERE tag.achievement_id = a.achievement_id
              AND tag.dimension = 'tech_field'
        ),
        '[]'::jsonb
    ) AS tech_fields,

    COALESCE(
        (
            SELECT jsonb_agg(tag.code ORDER BY tag.code)
            FROM achievement_tag AS tag
            WHERE tag.achievement_id = a.achievement_id
              AND tag.dimension = 'application_scenario'
        ),
        '[]'::jsonb
    ) AS application_scenarios
"""


def to_achievement(row, detail=False):
    result = dict(row)

    abstract = result.get("abstract_original")
    if abstract is not None:
        # 300 characters maximum, including the ellipsis.
        result["abstract_preview"] = (
            abstract[:299] + "…"
            if len(abstract) > 300
            else abstract
        )
    else:
        result["abstract_preview"] = None

    # Optional JSON arrays must not be invented.
    for field in (
        "tech_fields",
        "application_scenarios",
        "keywords",
        "topics",
        "key_metrics",
        "process",
    ):
        if result.get(field) is None:
            result[field] = []

    if not detail:
        detail_only = (
            "abstract_original",
            "doi",
            "venue",
            "keywords",
            "topics",
            "clean_status",
            "review_status",
            "trl_evidence",
            "key_metrics",
            "material_system",
            "process",
            "ip_status",
        )

        for field in detail_only:
            result.pop(field, None)

    return result


# ---------- GET /api/v1/achievements ----------

@router.get(
    "",
    response_model=AchievementListResponse,
    summary="List achievements",
)
def list_achievements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tech_field: str | None = None,
    publication_year: int | None = None,
    trl_min: int | None = Query(default=None, ge=1, le=9),
    trl_max: int | None = Query(default=None, ge=1, le=9),
    keyword: str | None = None,
    publication_status: Literal[
        "all", "unpublished", "mine"
    ] = "all",
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    if (
        trl_min is not None
        and trl_max is not None
        and trl_min > trl_max
    ):
        raise HTTPException(
            status_code=400,
            detail="trl_min cannot exceed trl_max",
        )

    conditions = []
    params = {}

    if publication_status == "unpublished":
        conditions.append("a.publisher_user_id IS NULL")

    elif publication_status == "mine":
        user = get_current_user(
            credentials=credentials,
            db=db,
        )
        conditions.append("a.publisher_user_id = :user_id")
        params["user_id"] = user["user_id"]

    if tech_field is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM achievement_tag AS tag_filter
                WHERE tag_filter.achievement_id = a.achievement_id
                  AND tag_filter.dimension = 'tech_field'
                  AND tag_filter.code = :tech_field
            )
        """)
        params["tech_field"] = tech_field

    if publication_year is not None:
        conditions.append(
            "a.publication_year = :publication_year"
        )
        params["publication_year"] = publication_year

    if trl_min is not None:
        conditions.append("ext.trl >= :trl_min")
        params["trl_min"] = trl_min

    if trl_max is not None:
        conditions.append("ext.trl <= :trl_max")
        params["trl_max"] = trl_max

    if keyword:
        conditions.append("""
            (
                a.title_original ILIKE :keyword
                OR a.abstract_original ILIKE :keyword
                OR profile.text ILIKE :keyword
            )
        """)
        params["keyword"] = f"%{keyword}%"

    where_sql = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    total = db.execute(
        text(f"""
            SELECT COUNT(*)
            {FROM_SQL}
            {where_sql}
        """),
        params,
    ).scalar_one()

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    rows = db.execute(
        text(f"""
            {SELECT_SQL}
            {FROM_SQL}
            {where_sql}
            ORDER BY a.achievement_id
            LIMIT :limit
            OFFSET :offset
        """),
        params,
    ).mappings().all()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                to_achievement(row)
                for row in rows
            ],
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


# ---------- GET /api/v1/achievements/{achievement_id} ----------

@router.get(
    "/{achievement_id}",
    response_model=AchievementDetailResponse,
    summary="Get achievement details",
)
def get_achievement(
    achievement_id: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(f"""
            {SELECT_SQL}
            {FROM_SQL}
            WHERE a.achievement_id = :achievement_id
        """),
        {"achievement_id": achievement_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Achievement not found",
        )

    return {
        "code": 0,
        "message": "success",
        "data": to_achievement(row, detail=True),
    }
