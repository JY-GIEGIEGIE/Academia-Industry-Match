# ============================================================
# 企业技术需求查询 API
#
# 功能说明：
# 1. 提供企业技术需求列表与详情查询接口
# 2. 支持技术领域、TRL、地区、需求状态及合作模式筛选
# 3. 支持发布状态筛选（all / unpublished / mine）及分页查询
# 4. 通过 JWT 认证获取当前用户，确保 mine 仅返回本人发布的需求
# 5. 关联企业公开画像，不返回企业真实名称及敏感联系方式
# 6. 统一使用 API v0.1.2 响应格式及错误处理规范
#
# 数据来源：demand、enterprise
# 接口：
#   GET /api/v1/demands
#   GET /api/v1/demands/{demand_id}
# ============================================================

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import get_current_user, security
from backend.database import get_db


router = APIRouter(
    prefix="/api/v1/demands",
    tags=["Demands"],
)


# ---------- Response models ----------

class EnterpriseSummary(BaseModel):
    display_name: str
    industry: str
    size: str


class DemandSummary(BaseModel):
    demand_id: str
    enterprise_id: str
    enterprise: EnterpriseSummary
    title: str
    pain_point: str
    required_trl: int
    status: Literal["draft", "active", "expired", "closed"]
    tech_fields: list[str] = Field(default_factory=list)
    application_scenarios: list[str] = Field(default_factory=list)
    is_simulated: bool
    dataset_version: str
    publisher_user_id: str | None = None
    published_at: datetime | None = None


class DemandDetail(DemandSummary):
    expected_solution: str
    technical_metrics: list[dict[str, Any]] = Field(
        default_factory=list
    )
    budget_range: str | None = None
    timeline: str | None = None
    cooperation_modes: list[str] = Field(default_factory=list)
    ip_requirement: str | None = None
    region: str
    valid_until: date
    source_note: str


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class DemandListData(BaseModel):
    items: list[DemandSummary]
    pagination: Pagination


class DemandListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: DemandListData


class DemandDetailResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: DemandDetail


# ---------- SQL ----------

FROM_SQL = """
FROM demand AS d
JOIN enterprise AS e
    ON e.enterprise_id = d.enterprise_id
"""

SELECT_SQL = """
SELECT
    d.demand_id,
    d.enterprise_id,
    d.title,
    d.pain_point,
    d.expected_solution,
    d.technical_metrics,
    d.budget_range,
    d.timeline,
    d.cooperation_modes,
    d.required_trl,
    d.tech_fields,
    d.application_scenarios,
    d.ip_requirement,
    d.region,
    d.status,
    d.valid_until,
    d.is_simulated,
    d.source_note,
    d.dataset_version,
    d.publisher_user_id,
    d.published_at,

    e.display_name AS enterprise_display_name,
    e.industry AS enterprise_industry,
    e.size AS enterprise_size
"""


def to_demand(row, detail=False):
    result = dict(row)

    result["enterprise"] = {
        "display_name": result.pop(
            "enterprise_display_name"
        ),
        "industry": result.pop("enterprise_industry"),
        "size": result.pop("enterprise_size"),
    }

    for field in (
        "technical_metrics",
        "cooperation_modes",
        "tech_fields",
        "application_scenarios",
    ):
        if result.get(field) is None:
            result[field] = []

    if not detail:
        detail_only = (
            "expected_solution",
            "technical_metrics",
            "budget_range",
            "timeline",
            "cooperation_modes",
            "ip_requirement",
            "region",
            "valid_until",
            "source_note",
        )

        for field in detail_only:
            result.pop(field, None)

    return result


# ---------- GET /api/v1/demands ----------

@router.get(
    "",
    response_model=DemandListResponse,
    summary="List enterprise demands",
)
def list_demands(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tech_field: str | None = None,
    required_trl: int | None = Query(
        default=None, ge=1, le=9
    ),
    region: str | None = None,
    status: Literal["draft", "active", "expired", "closed"] | None = None,
    cooperation_mode: str | None = None,
    publication_status: Literal[
        "all", "unpublished", "mine"
    ] = "all",
    credentials: HTTPAuthorizationCredentials | None = Depends(
        security
    ),
    db: Session = Depends(get_db),
):
    conditions = []
    params = {}

    if publication_status == "unpublished":
        conditions.append("d.publisher_user_id IS NULL")

    elif publication_status == "mine":
        user = get_current_user(
            credentials=credentials,
            db=db,
        )
        conditions.append(
            "d.publisher_user_id = :user_id"
        )
        params["user_id"] = user["user_id"]

    if tech_field is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(
                    COALESCE(to_jsonb(d.tech_fields), '[]'::jsonb)
                ) AS field(code)
                WHERE field.code = :tech_field
            )
        """)
        params["tech_field"] = tech_field

    if required_trl is not None:
        conditions.append(
            "d.required_trl = :required_trl"
        )
        params["required_trl"] = required_trl

    if region is not None:
        conditions.append("d.region = :region")
        params["region"] = region

    if status is not None:
        conditions.append("d.status = :status")
        params["status"] = status

    if cooperation_mode is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(
                    COALESCE(
                        to_jsonb(d.cooperation_modes),
                        '[]'::jsonb
                    )
                ) AS mode(code)
                WHERE mode.code = :cooperation_mode
            )
        """)
        params["cooperation_mode"] = cooperation_mode

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
            ORDER BY d.demand_id
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [
                to_demand(row)
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


# ---------- GET /api/v1/demands/{demand_id} ----------

@router.get(
    "/{demand_id}",
    response_model=DemandDetailResponse,
    summary="Get enterprise demand details",
)
def get_demand(
    demand_id: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(f"""
            {SELECT_SQL}
            {FROM_SQL}
            WHERE d.demand_id = :demand_id
        """),
        {"demand_id": demand_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Demand not found",
        )

    return {
        "code": 0,
        "message": "success",
        "data": to_demand(row, detail=True),
    }
