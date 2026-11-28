# ============================================================
# 成果与需求发布及事务处理测试

# 功能说明：
# 1. 验证科研成果与企业需求发布及 dispatch 创建
# 2. 验证不存在记录、重复发布和不允许文本编辑
# 3. 验证发布过程异常时调用事务回滚
# 4. 验证异步匹配任务提交与 Broker 故障响应
# 5. 验证错误角色不会修改数据库
#
# 测试方式：pytest + TestClient + MagicMock + patch
# 测试文件：tests/test_publishing_api.py
# ============================================================

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.routers.publishing import publish_record
from tests.conftest import ENTERPRISE, RESEARCHER

def publication_db(result_id):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = result_id
    return db


@pytest.mark.parametrize(
    "kind,record_id,user",
    [
        ("achievement", "ach_001", RESEARCHER),
        ("demand", "dem_001", ENTERPRISE),
    ],
)
def test_publish_record_commits_transaction(
    kind, record_id, user
):
    db = publication_db(record_id)

    run_id = publish_record(
        db,
        kind,
        record_id,
        user["user_id"],
        {},
    )

    assert run_id.startswith("run_")
    assert db.execute.call_count == 2
    db.commit.assert_called_once()

    sql = str(db.execute.call_args_list[1].args[0])
    params = db.execute.call_args_list[1].args[1]

    assert "INSERT INTO match_dispatch" in sql
    assert params["object_type"] == kind
    assert params["object_id"] == record_id
    assert params["run_id"] == run_id


@pytest.mark.parametrize("kind", ["achievement", "demand"])
def test_missing_record_returns_404(kind):
    db = MagicMock()

    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        publish_record(
            db, kind, "missing", RESEARCHER["user_id"], {}
        )

    assert exc.value.status_code == 404
    db.rollback.assert_called()


@pytest.mark.parametrize("kind", ["achievement", "demand"])
def test_duplicate_publication_returns_409(kind):
    db = MagicMock()

    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.first.return_value = (1,)

    with pytest.raises(HTTPException) as exc:
        publish_record(
            db, kind, "already_published",
            RESEARCHER["user_id"], {}
        )

    assert exc.value.status_code == 409
    db.rollback.assert_called()


def test_updates_not_allowed():
    db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        publish_record(
            db,
            "achievement",
            "ach_001",
            RESEARCHER["user_id"],
            {"title_original": "Changed"},
        )

    assert exc.value.status_code == 422
    db.execute.assert_not_called()


def test_dispatch_insert_failure_rolls_back():
    db = MagicMock()

    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: "dem_001"),
        RuntimeError("Dispatch insert failed"),
    ]

    with pytest.raises(RuntimeError):
        publish_record(
            db,
            "demand",
            "dem_001",
            ENTERPRISE["user_id"],
            {},
        )

    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_achievement_http_success(researcher, db):
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: "ach_001"),
        MagicMock(),
    ]

    with patch(
        "backend.routers.publishing.submit_matching_job"
    ) as submit:
        response = researcher.post(
            "/api/v1/achievements",
            json={"achievement_id": "ach_001", "updates": {}},
        )

    assert response.status_code == 200

    data = response.json()["data"]
    assert data["achievement_id"] == "ach_001"
    assert data["run_id"].startswith("run_")

    submit.assert_called_once_with(db, data["run_id"])


def test_demand_http_success(enterprise, db):
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: "dem_001"),
        MagicMock(),
    ]

    with patch(
        "backend.routers.publishing.submit_matching_job"
    ) as submit:
        response = enterprise.post(
            "/api/v1/demands",
            json={"demand_id": "dem_001", "updates": {}},
        )

    assert response.status_code == 200
    submit.assert_called_once()


def test_enqueue_failure_returns_503(researcher, db):
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: "ach_001"),
        MagicMock(),
    ]

    with patch(
        "backend.routers.publishing.submit_matching_job",
        side_effect=HTTPException(
            status_code=503,
            detail="Redis unavailable",
        ),
    ):
        response = researcher.post(
            "/api/v1/achievements",
            json={"achievement_id": "ach_001", "updates": {}},
        )

    assert response.status_code == 503
    db.commit.assert_called_once()


def test_wrong_role_does_not_write_db(researcher, db):
    response = researcher.post(
        "/api/v1/demands",
        json={"demand_id": "dem_001", "updates": {}},
    )

    assert response.status_code == 403
    db.execute.assert_not_called()
