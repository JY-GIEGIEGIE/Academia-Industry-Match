
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import require_role
from backend.database import get_db

router = APIRouter(prefix="/api/v1", tags=["Publishing"])


class AchievementPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    achievement_id: str = Field(min_length=1)
    updates: dict[str, Any] = Field(default_factory=dict)


class DemandPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demand_id: str = Field(min_length=1)
    updates: dict[str, Any] = Field(default_factory=dict)


class AchievementPublishData(BaseModel):
    achievement_id: str
    run_id: str


class DemandPublishData(BaseModel):
    demand_id: str
    run_id: str


class AchievementPublishResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: AchievementPublishData


class DemandPublishResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: DemandPublishData


def publish_record(
    db: Session,
    record_type: str,
    record_id: str,
    user_id: str,
    updates: dict,
):
    # MVP: only existing records, with no text edits.
    if updates:
        raise HTTPException(
            status_code=422,
            detail="updates must be empty for MVP",
        )

    run_id = f"run_{uuid4().hex}"

    if record_type == "achievement":
        query = text("""
            UPDATE achievement
            SET publisher_user_id = :user_id,
                published_at = now(),
                clean_status = 'published'
            WHERE achievement_id = :record_id
              AND publisher_user_id IS NULL
            RETURNING achievement_id
        """)
    elif record_type == "demand":
        query = text("""
            UPDATE demand
            SET publisher_user_id = :user_id,
                published_at = now(),
                status = 'active'
            WHERE demand_id = :record_id
              AND publisher_user_id IS NULL
            RETURNING demand_id
        """)
    else:
        raise ValueError("Unsupported record type")

    try:
        result = db.execute(
            query,
            {
                "user_id": user_id,
                "record_id": record_id,
            },
        ).scalar_one_or_none()

        if result is None:
            table = (
                "achievement"
                if record_type == "achievement"
                else "demand"
            )
            id_column = (
                "achievement_id"
                if record_type == "achievement"
                else "demand_id"
            )

            exists = db.execute(
                text(
                    f"SELECT 1 FROM {table} "
                    f"WHERE {id_column} = :record_id"
                ),
                {"record_id": record_id},
            ).first()

            db.rollback()

            if exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="Record not found",
                )

            raise HTTPException(
                status_code=409,
                detail="Record already published",
            )

        # Persist publication before triggering matching.
        db.commit()

    except Exception:
        db.rollback()
        raise

    return run_id


@router.post(
    "/achievements",
    response_model=AchievementPublishResponse,
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Researcher role required"},
        404: {"description": "Achievement not found"},
        409: {"description": "Already published"},
        503: {"description": "Matching queue unavailable"},
    },
)
def publish_achievement(
    request: AchievementPublishRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("researcher")),
):
    from backend.tasks import run_match_for_achievement

    run_id = publish_record(
        db=db,
        record_type="achievement",
        record_id=request.achievement_id,
        user_id=user["user_id"],
        updates=request.updates,
    )

    try:
        run_match_for_achievement.delay(
            request.achievement_id,
            run_id,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Publication saved, but matching enqueue failed",
        )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "achievement_id": request.achievement_id,
            "run_id": run_id,
        },
    }


@router.post(
    "/demands",
    response_model=DemandPublishResponse,
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Enterprise role required"},
        404: {"description": "Demand not found"},
        409: {"description": "Already published"},
        503: {"description": "Matching queue unavailable"},
    },
)
def publish_demand(
    request: DemandPublishRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("enterprise")),
):
    from backend.tasks import run_match_for_demand

    run_id = publish_record(
        db=db,
        record_type="demand",
        record_id=request.demand_id,
        user_id=user["user_id"],
        updates=request.updates,
    )

    try:
        run_match_for_demand.delay(
            request.demand_id,
            run_id,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Publication saved, but matching enqueue failed",
        )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "demand_id": request.demand_id,
            "run_id": run_id,
        },
    }
