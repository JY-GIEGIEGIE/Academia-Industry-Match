# ============================================================
# 匹配任务重试接口与访问权限测试

# 功能说明：
# 1. 验证任务不存在、发布者不匹配及角色错误
# 2. 验证不可重试状态和已启动任务返回 HTTP 409
# 3. 验证 retryable 任务可重试并返回 HTTP 202
# 4. 验证超时 submitting 回收和未超时拒绝
# 5. 验证 Broker 再次不可用时返回 HTTP 503
#
# 测试方式：pytest + TestClient + MagicMock（模拟投递）
# 测试文件：tests/test_pipeline_retry_api.py
# ============================================================

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import ENTERPRISE, OTHER_RESEARCHER, RESEARCHER

def dispatch_row(
    kind="demand",
    status="retryable",
    claimed_at=None,
):
    user = RESEARCHER if kind == "achievement" else ENTERPRISE

    return {
        "run_id": "run_123",
        "object_type": kind,
        "object_id": "ach_001" if kind == "achievement" else "dem_001",
        "publisher_user_id": user["user_id"],
        "dispatch_status": status,
        "claimed_at": claimed_at,
    }


def configure_db(db, row, owner=None, run_status=None):
    """
    The endpoint executes:
    1. SELECT match_dispatch
    2. SELECT publication owner
    3. SELECT pipeline_run
    """
    dispatch = MagicMock()
    dispatch.mappings.return_value.first.return_value = row

    publication = MagicMock()
    publication.scalar_one_or_none.return_value = owner

    pipeline = MagicMock()
    pipeline.scalar_one_or_none.return_value = run_status

    db.execute.side_effect = [
        dispatch,
        publication,
        pipeline,
    ]


def test_unknown_dispatch_returns_404(researcher, db):
    configure_db(db, None)

    response = researcher.post(
        "/api/v1/pipeline-runs/run_unknown/retry"
    )

    assert response.status_code == 404


def test_other_user_returns_403(client, login_as, db):
    login_as(OTHER_RESEARCHER)

    configure_db(
        db,
        dispatch_row(kind="achievement"),
    )

    response = client.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 403


def test_wrong_role_returns_403(client, login_as, db):
    login_as({
        **ENTERPRISE,
        "user_id": RESEARCHER["user_id"],
    })

    configure_db(
        db,
        dispatch_row(kind="achievement"),
    )

    response = client.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 403


def test_publication_owner_mismatch(enterprise, db):
    configure_db(
        db,
        dispatch_row(),
        owner="another_user",
    )

    response = enterprise.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "status",
    ["pending", "submitted", "submitting"],
)
def test_non_retryable_states_return_409(
    enterprise, db, status
):
    configure_db(
        db,
        dispatch_row(status=status),
        owner=ENTERPRISE["user_id"],
    )

    response = enterprise.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 409


def test_started_pipeline_returns_409(enterprise, db):
    configure_db(
        db,
        dispatch_row(),
        owner=ENTERPRISE["user_id"],
        run_status="running",
    )

    response = enterprise.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 409


def test_retry_success(enterprise, db):
    configure_db(
        db,
        dispatch_row(),
        owner=ENTERPRISE["user_id"],
    )

    with patch(
        "backend.routers.pipeline_runs.submit_matching_job"
    ) as submit:
        response = enterprise.post(
            "/api/v1/pipeline-runs/run_123/retry"
        )

    assert response.status_code == 202
    assert response.json()["data"] == {
        "run_id": "run_123",
        "dispatch_status": "submitted",
    }

    submit.assert_called_once_with(db, "run_123")


def test_stale_submitting_allowed(enterprise, db):
    claimed_at = datetime.now(timezone.utc) - timedelta(
        minutes=6
    )

    configure_db(
        db,
        dispatch_row(
            status="submitting",
            claimed_at=claimed_at,
        ),
        owner=ENTERPRISE["user_id"],
    )

    with patch(
        "backend.routers.pipeline_runs.submit_matching_job"
    ) as submit:
        response = enterprise.post(
            "/api/v1/pipeline-runs/run_123/retry"
        )

    assert response.status_code == 202
    submit.assert_called_once()


def test_recent_submitting_rejected(enterprise, db):
    claimed_at = datetime.now(timezone.utc) - timedelta(
        minutes=1
    )

    configure_db(
        db,
        dispatch_row(
            status="submitting",
            claimed_at=claimed_at,
        ),
        owner=ENTERPRISE["user_id"],
    )

    response = enterprise.post(
        "/api/v1/pipeline-runs/run_123/retry"
    )

    assert response.status_code == 409


def test_retry_broker_unavailable(enterprise, db):
    from fastapi import HTTPException

    configure_db(
        db,
        dispatch_row(),
        owner=ENTERPRISE["user_id"],
    )

    with patch(
        "backend.routers.pipeline_runs.submit_matching_job",
        side_effect=HTTPException(503, "Broker unavailable"),
    ):
        response = enterprise.post(
            "/api/v1/pipeline-runs/run_123/retry"
        )

    assert response.status_code == 503
