# ============================================================
# Celery 匹配任务投递与恢复测试

# 功能说明：
# 1. 验证任务原子认领 SQL 及超时重试条件
# 2. 验证成果与需求任务的正确 Celery 路由
# 3. 验证 run_id 复用与提交成功状态更新
# 4. 验证 Broker 异常时返回 HTTP 503 并记录 retryable
# 5. 验证重复认领 HTTP 409 与数据库异常回滚
#
# 测试方式：pytest + MagicMock + patch（不启动真实 Worker）
# 测试文件：tests/test_match_dispatch.py
# ============================================================

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.match_dispatch import (
    STALE_SUBMITTING_SECONDS,
    submit_matching_job,
)


def claimed_db(kind="demand", object_id="dem_test"):
    db = MagicMock()
    db.execute.return_value.mappings.return_value.first.return_value = {
        "object_type": kind,
        "object_id": object_id,
    }
    return db


def rejected_db():
    db = MagicMock()
    db.execute.return_value.mappings.return_value.first.return_value = None
    return db


def test_stale_timeout():
    assert STALE_SUBMITTING_SECONDS == 300


def test_claim_sql_supports_pending_retryable_and_stale():
    db = rejected_db()

    with pytest.raises(HTTPException):
        submit_matching_job(db, "run_test")

    sql = str(db.execute.call_args.args[0])
    params = db.execute.call_args.args[1]

    assert "'pending'" in sql
    assert "'retryable'" in sql
    assert "dispatch_status = 'submitting'" in sql
    assert "claimed_at" in sql
    assert params["stale_seconds"] == 300


@pytest.mark.parametrize(
    "kind,object_id,task_name",
    [
        (
            "demand",
            "dem_test",
            "run_match_for_demand",
        ),
        (
            "achievement",
            "ach_test",
            "run_match_for_achievement",
        ),
    ],
)
def test_correct_celery_task(kind, object_id, task_name):
    db = claimed_db(kind, object_id)
    run_id = "run_same_id"

    path = f"backend.tasks.{task_name}.apply_async"

    with patch(path) as send_task:
        returned_id = submit_matching_job(db, run_id)

    assert returned_id == run_id
    send_task.assert_called_once()

    assert send_task.call_args.kwargs["task_id"] == run_id
    assert send_task.call_args.kwargs["args"] == [
        object_id,
        run_id,
    ]

    assert db.commit.call_count == 2


def test_celery_retry_policy():
    db = claimed_db()

    with patch(
        "backend.tasks.run_match_for_demand.apply_async"
    ) as send_task:
        submit_matching_job(db, "run_retry_policy")

    kwargs = send_task.call_args.kwargs

    assert kwargs["retry"] is True
    assert kwargs["retry_policy"]["max_retries"] == 3


def test_claim_failure_returns_409():
    db = rejected_db()

    with pytest.raises(HTTPException) as exc:
        submit_matching_job(db, "run_duplicate")

    assert exc.value.status_code == 409
    assert db.commit.call_count == 1


def test_broker_failure_returns_503():
    db = claimed_db()

    with patch(
        "backend.tasks.run_match_for_demand.apply_async",
        side_effect=ConnectionError("Redis unavailable"),
    ):
        with pytest.raises(HTTPException) as exc:
            submit_matching_job(db, "run_failed")

    assert exc.value.status_code == 503
    assert db.commit.call_count == 2

    final_sql = str(db.execute.call_args.args[0])
    assert "dispatch_status = 'retryable'" in final_sql


def test_broker_error_not_returned_to_client():
    db = claimed_db()

    with patch(
        "backend.tasks.run_match_for_demand.apply_async",
        side_effect=RuntimeError("SECRET_BROKER_INTERNAL_ERROR"),
    ):
        with pytest.raises(HTTPException) as exc:
            submit_matching_job(db, "run_failed")

    assert exc.value.status_code == 503
    assert "SECRET_BROKER_INTERNAL_ERROR" not in str(
        exc.value.detail
    )


def test_success_marks_submitted():
    db = claimed_db()

    with patch(
        "backend.tasks.run_match_for_demand.apply_async"
    ):
        submit_matching_job(db, "run_success")

    final_sql = str(db.execute.call_args.args[0])
    assert "dispatch_status = 'submitted'" in final_sql
    assert "submitted_at" in final_sql


def test_database_claim_error_rolls_back():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("DB unavailable")

    with pytest.raises(RuntimeError):
        submit_matching_job(db, "run_db_failure")

    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_no_task_sent_after_failed_claim():
    db = rejected_db()

    with patch(
        "backend.tasks.run_match_for_demand.apply_async"
    ) as send:
        with pytest.raises(HTTPException):
            submit_matching_job(db, "run_duplicate")

    send.assert_not_called()
