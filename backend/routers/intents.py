# ============================================================
# 产学研合作意向管理 API
#
# 功能说明：
# 1. 科研人员或企业用户可对成果与需求表达合作意向
# 2. 验证用户身份和对应成果、需求的发布权限
# 3. 防止相同成果与需求组合重复创建合作意向
# 4. 支持合作意向列表查询、筛选及分页
# 5. 仅允许另一方确认或拒绝合作意向
# 6. 合作确认后向双方开放模拟联系方式
# 7. 使用统一 API 响应格式及错误处理规范
#
# 状态流转：
#   expressed -> confirmed
#   expressed -> declined
#
# 数据来源：intent、achievement、demand、match_score
#
# 接口：
#   POST /api/v1/intents
#   GET  /api/v1/intents
#   POST /api/v1/intents/{intent_id}/confirm
#   POST /api/v1/intents/{intent_id}/decline
#   GET  /api/v1/intents/{intent_id}/contact
# ============================================================

from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db


router = APIRouter(
    prefix="/api/v1/intents",
    tags=["Collaboration Intents"],
)


# ============================================================
# Response models
# ============================================================

IntentStatus = Literal[
    "expressed",
    "confirmed",
    "declined",
    "closed",
]


class IntentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    achievement_id: str = Field(min_length=1)
    demand_id: str = Field(min_length=1)


class IntentData(BaseModel):
    intent_id: str
    achievement_id: str
    demand_id: str

    match_id: str | None = None
    initiator_user_id: str
    status: IntentStatus
    contact_revealed: bool

    achievement_title: str
    demand_title: str

    created_at: datetime
    updated_at: datetime


class IntentResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: IntentData


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class IntentListData(BaseModel):
    items: list[IntentData]
    pagination: Pagination


class IntentListResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: IntentListData


class ContactInfo(BaseModel):
    name: str
    email: str
    phone: str


class ContactData(BaseModel):
    intent_id: str
    status: Literal["confirmed"] = "confirmed"

    # 两个独立的模拟联系人，与 S-14 前端保持一致。
    researcher_contact: ContactInfo
    enterprise_contact: ContactInfo

    is_simulated: Literal[True] = True

class ContactResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: ContactData


# ============================================================
# Database helpers
# ============================================================

def get_pair(
    db: Session,
    achievement_id: str,
    demand_id: str,
):
    """
    查询成果与需求组合，并获取双方发布者。
    """

    return db.execute(
        text("""
            SELECT
                a.achievement_id,
                a.title_original AS achievement_title,
                a.publisher_user_id AS researcher_id,

                d.demand_id,
                d.title AS demand_title,
                d.publisher_user_id AS enterprise_id

            FROM achievement AS a
            CROSS JOIN demand AS d

            WHERE a.achievement_id = :achievement_id
              AND d.demand_id = :demand_id
        """),
        {
            "achievement_id": achievement_id,
            "demand_id": demand_id,
        },
    ).mappings().first()


def latest_match_id(
    db: Session,
    achievement_id: str,
    demand_id: str,
):
    """
    查询最新有效匹配结果。
    没有匹配结果时返回 None。
    """

    return db.execute(
        text("""
            SELECT match_id
            FROM match_score

            WHERE achievement_id = :achievement_id
              AND demand_id = :demand_id
              AND is_stale = false

            ORDER BY created_at DESC, match_id DESC
            LIMIT 1
        """),
        {
            "achievement_id": achievement_id,
            "demand_id": demand_id,
        },
    ).scalar_one_or_none()


def user_is_participant(
    user: dict,
    pair,
) -> bool:
    """
    判断当前用户是否为成果或需求的发布者。
    """

    if user["role"] == "researcher":
        return (
            pair["researcher_id"] == user["user_id"]
        )

    if user["role"] == "enterprise":
        return (
            pair["enterprise_id"] == user["user_id"]
        )

    return False


def get_intent(
    db: Session,
    intent_id: str,
    lock: bool = False,
):
    """
    查询单条合作意向及双方发布者。
    修改状态时可使用行锁防止并发冲突。
    """

    lock_sql = "FOR UPDATE OF i" if lock else ""

    row = db.execute(
        text(f"""
            SELECT
                i.intent_id,
                i.achievement_id,
                i.demand_id,
                i.initiator_user_id,
                i.status,
                i.contact_revealed,
                i.created_at,
                i.updated_at,

                a.title_original AS achievement_title,
                d.title AS demand_title,

                a.publisher_user_id AS researcher_id,
                d.publisher_user_id AS enterprise_id

            FROM intent AS i

            JOIN achievement AS a
              ON a.achievement_id = i.achievement_id

            JOIN demand AS d
              ON d.demand_id = i.demand_id

            WHERE i.intent_id = :intent_id
            {lock_sql}
        """),
        {"intent_id": intent_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Intent not found",
        )

    return row


def to_intent_data(
    db: Session,
    row,
):
    """
    将数据库记录转换为公开 API 响应。
    移除内部权限字段，保留 contact_revealed 供前端判断联系方式是否开放。
    """

    result = dict(row)

    result.pop("researcher_id", None)
    result.pop("enterprise_id", None)

    result["match_id"] = latest_match_id(
        db,
        row["achievement_id"],
        row["demand_id"],
    )

    return result


# ============================================================
# POST /api/v1/intents
# ============================================================

@router.post(
    "",
    response_model=IntentResponse,
    status_code=201,
    summary="Express collaboration interest",
)
def create_intent(
    request: IntentCreateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # 1. 确认成果与需求均存在。
    pair = get_pair(
        db,
        request.achievement_id,
        request.demand_id,
    )

    if pair is None:
        raise HTTPException(
            status_code=404,
            detail="Achievement or demand not found",
        )

    # 2. 只有对应成果或需求的发布者可以表达意向。
    if not user_is_participant(user, pair):
        raise HTTPException(
            status_code=403,
            detail="You cannot represent this collaboration party",
        )

    # 3. 合作双方必须都已发布对应记录。
    if (
        pair["researcher_id"] is None
        or pair["enterprise_id"] is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Both records must be published",
        )

    # 4. 检查是否已有相同的合作意向。
    existing = db.execute(
        text("""
            SELECT intent_id
            FROM intent

            WHERE achievement_id = :achievement_id
              AND demand_id = :demand_id

            LIMIT 1
        """),
        {
            "achievement_id": request.achievement_id,
            "demand_id": request.demand_id,
        },
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Collaboration intent already exists",
        )

    # 5. 创建合作意向。
    # S-12 数据库默认状态为 expressed。
    intent_id = f"intent_{uuid4().hex}"

    try:
        db.execute(
            text("""
                INSERT INTO intent (
                    intent_id,
                    achievement_id,
                    demand_id,
                    initiator_user_id,
                    status,
                    contact_revealed,
                    created_at,
                    updated_at
                )
                VALUES (
                    :intent_id,
                    :achievement_id,
                    :demand_id,
                    :initiator_user_id,
                    'expressed',
                    false,
                    now(),
                    now()
                )
            """),
            {
                "intent_id": intent_id,
                "achievement_id": request.achievement_id,
                "demand_id": request.demand_id,
                "initiator_user_id": user["user_id"],
            },
        )

        db.commit()

    except IntegrityError:
        db.rollback()

        # 唯一约束等数据完整性错误。
        raise HTTPException(
            status_code=409,
            detail="Collaboration intent conflicts with existing data",
        )

    # 6. 返回创建成功的合作意向。
    row = get_intent(db, intent_id)

    return {
        "code": 0,
        "message": "success",
        "data": to_intent_data(db, row),
    }


# ============================================================
# GET /api/v1/intents
# ============================================================

@router.get(
    "",
    response_model=IntentListResponse,
    summary="List collaboration intents",
)
def list_intents(
    achievement_id: str | None = None,
    demand_id: str | None = None,
    status: IntentStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conditions = []
    params = {
        "user_id": user["user_id"],
    }

    # 仅返回当前用户参与的合作意向。
    if user["role"] == "researcher":
        conditions.append(
            "a.publisher_user_id = :user_id"
        )

    elif user["role"] == "enterprise":
        conditions.append(
            "d.publisher_user_id = :user_id"
        )

    else:
        raise HTTPException(
            status_code=403,
            detail="Invalid user role",
        )

    # 按成果 ID 筛选。
    if achievement_id is not None:
        conditions.append(
            "i.achievement_id = :achievement_id"
        )
        params["achievement_id"] = achievement_id

    # 按需求 ID 筛选。
    if demand_id is not None:
        conditions.append(
            "i.demand_id = :demand_id"
        )
        params["demand_id"] = demand_id

    # 按合作意向状态筛选。
    if status is not None:
        conditions.append("i.status = :status")
        params["status"] = status

    where_sql = " AND ".join(conditions)

    from_sql = """
        FROM intent AS i

        JOIN achievement AS a
          ON a.achievement_id = i.achievement_id

        JOIN demand AS d
          ON d.demand_id = i.demand_id
    """

    # 查询总记录数。
    total = db.execute(
        text(f"""
            SELECT COUNT(*)
            {from_sql}
            WHERE {where_sql}
        """),
        params,
    ).scalar_one()

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    # 查询当前页。
    rows = db.execute(
        text(f"""
            SELECT
                i.intent_id,
                i.achievement_id,
                i.demand_id,
                i.initiator_user_id,
                i.status,
                i.contact_revealed,
                i.created_at,
                i.updated_at,

                a.title_original AS achievement_title,
                d.title AS demand_title

            {from_sql}

            WHERE {where_sql}

            ORDER BY i.created_at DESC, i.intent_id DESC

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
                to_intent_data(db, row)
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


# ============================================================
# Shared confirmation / decline logic
# ============================================================

def change_intent_status(
    db: Session,
    intent_id: str,
    user: dict,
    new_status: Literal["confirmed", "declined"],
):
    try:
        # 1. 锁定记录，避免双方重复或并发修改。
        row = get_intent(
            db,
            intent_id,
            lock=True,
        )

        # 2. 当前用户必须属于合作双方之一。
        if not user_is_participant(user, row):
            raise HTTPException(
                status_code=403,
                detail="Not a collaboration participant",
            )

        # 3. 发起方不能自行确认或拒绝。
        if row["initiator_user_id"] == user["user_id"]:
            raise HTTPException(
                status_code=403,
                detail="The initiator cannot confirm or decline",
            )

        # 4. 仅 expressed 状态允许变更。
        if row["status"] != "expressed":
            raise HTTPException(
                status_code=409,
                detail="Intent is no longer awaiting confirmation",
            )

        # 5. 确认时开放模拟联系方式。
        contact_revealed = (
            new_status == "confirmed"
        )

        db.execute(
            text("""
                UPDATE intent

                SET status = :new_status,
                    contact_revealed = :contact_revealed,
                    updated_at = now()

                WHERE intent_id = :intent_id
                  AND status = 'expressed'
            """),
            {
                "new_status": new_status,
                "contact_revealed": contact_revealed,
                "intent_id": intent_id,
            },
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    updated = get_intent(db, intent_id)

    return {
        "code": 0,
        "message": "success",
        "data": to_intent_data(db, updated),
    }


# ============================================================
# POST /api/v1/intents/{intent_id}/confirm
# ============================================================

@router.post(
    "/{intent_id}/confirm",
    response_model=IntentResponse,
    summary="Confirm collaboration interest",
)
def confirm_intent(
    intent_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return change_intent_status(
        db=db,
        intent_id=intent_id,
        user=user,
        new_status="confirmed",
    )


# ============================================================
# POST /api/v1/intents/{intent_id}/decline
# ============================================================

@router.post(
    "/{intent_id}/decline",
    response_model=IntentResponse,
    summary="Decline collaboration interest",
)
def decline_intent(
    intent_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return change_intent_status(
        db=db,
        intent_id=intent_id,
        user=user,
        new_status="declined",
    )


# ============================================================
# GET /api/v1/intents/{intent_id}/contact
# ============================================================

@router.get(
    "/{intent_id}/contact",
    response_model=ContactResponse,
    summary="Get mock contact information",
)
def get_intent_contact(
    intent_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    row = get_intent(
        db=db,
        intent_id=intent_id,
    )

    # 1. 只有合作双方可以访问。
    if not user_is_participant(user, row):
        raise HTTPException(
            status_code=403,
            detail="Not a collaboration participant",
        )

    # 2. 必须已经确认并开放联系方式。
    if (
        row["status"] != "confirmed"
        or not row["contact_revealed"]
    ):
        raise HTTPException(
            status_code=403,
            detail="Contacts are available only after confirmation",
        )

    # 3. 返回双方模拟联系方式，不使用真实个人数据。
    return {
        "code": 0,
        "message": "success",
        "data": {
            "intent_id": intent_id,
            "status": "confirmed",
            "researcher_contact": {
                "name": "科研方演示联系人",
                "email": "researcher@example.invalid",
                "phone": "000-0000-0001",
            },
            "enterprise_contact": {
                "name": "企业方演示联系人",
                "email": "enterprise@example.invalid",
                "phone": "000-0000-0002",
            },
            "is_simulated": True,
        },
    }
