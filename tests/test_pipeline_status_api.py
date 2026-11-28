# ============================================================
# 匹配任务执行状态查询测试

# 功能说明：
# 1. 验证接口需要 JWT 认证
# 2. 验证任务不存在时返回 HTTP 404
# 3. 验证 running、success、partial、failed 四种状态
# 4. 验证时间字段和内部敏感字段不被暴露
#
# 测试方式：pytest + TestClient + MagicMock
# 测试文件：tests/test_pipeline_status_api.py
# ============================================================

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def test_status_requires_auth(client):
    response = client.get(
        "/api/v1/pipeline-runs/run_123"
    )

    assert response.status_code == 401


def test_status_not_found(researcher, db):
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = researcher.get(
        "/api/v1/pipeline-runs/run_unknown"
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40401


@pytest.mark.parametrize(
    "status",
    ["running", "success", "partial", "failed"],
)
def test_pipeline_status_values(researcher, db, status):
    now = datetime.now(timezone.utc)

    db.execute.return_value.mappings.return_value.first.return_value = {
        "run_id": "run_123",
        "stage": "match",
        "status": status,
        "started_at": now,
        "finished_at": None if status == "running" else now,
    }

    response = researcher.get(
        "/api/v1/pipeline-runs/run_123"
    )

    assert response.status_code == 200

    data = response.json()["data"]

    assert data["run_id"] == "run_123"
    assert data["stage"] == "match"
    assert data["status"] == status

    if status == "running":
        assert data["finished_at"] is None
    else:
        assert data["finished_at"] is not None

    assert "error" not in data
    assert "input_count" not in data
    assert "output_count" not in data
