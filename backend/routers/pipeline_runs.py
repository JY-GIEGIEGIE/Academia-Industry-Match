
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db

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
