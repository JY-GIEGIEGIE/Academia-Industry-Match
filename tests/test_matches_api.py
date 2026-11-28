# ============================================================
# 成果与需求匹配结果查询测试

# 功能说明：
# 1. 验证双向匹配结果查询、分页与分数过滤
# 2. 验证资源不存在时返回 HTTP 404
# 3. 验证 B2 结果的风险和证据可为 null
# 4. 验证详情字段隔离与关联数据缺失错误
#
# 测试方式：pytest + TestClient + MagicMock（模拟匹配表）
# 测试文件：tests/test_matches_api.py
# ============================================================

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.routers.matches import build_matches


def match_row():
    return {
        "match_id": "match_dem_001_ach_001",
        "achievement_id": "ach_001",
        "demand_id": "dem_001",
        "total_score": 88.0,
        "tag_score": 90.0,
        "semantic_score": 86.0,
        "llm_score": None,
        "reason": "Potential match",
        "risk": None,
        "evidence": None,
        "model": "b2",
        "prompt_version": "b2-rule-v1",
        "dataset_version": "v0.1.2",
        "taxonomy_version": "v0.1",
        "embedding_model_version": "test-embedding-v1",
        "is_stale": False,
        "created_at": datetime.now(timezone.utc),
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/demands/dem_001/matches?page=0",
        "/api/v1/achievements/ach_001/matches?page_size=101",
        "/api/v1/demands/dem_001/matches?min_score=-1",
        "/api/v1/achievements/ach_001/matches?min_score=101",
    ],
)
def test_match_filter_validation(client, endpoint):
    assert client.get(endpoint).status_code == 422


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/demands/missing/matches",
        "/api/v1/achievements/missing/matches",
    ],
)
def test_missing_matching_parent_returns_404(
    client, db, endpoint
):
    db.execute.return_value.first.return_value = None

    response = client.get(endpoint)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/demands/dem_001/matches",
        "/api/v1/achievements/ach_001/matches",
    ],
)
def test_empty_match_results(client, db, endpoint):
    exists = MagicMock()
    exists.first.return_value = (1,)

    count = MagicMock()
    count.scalar_one.return_value = 0

    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []

    db.execute.side_effect = [exists, count, rows]

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert response.json()["data"]["pagination"]["total"] == 0


def test_match_detail_not_found(client, db):
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = client.get("/api/v1/matches/missing")

    assert response.status_code == 404


def test_match_summary_removes_detail_fields():
    row = match_row()

    with (
        patch(
            "backend.routers.matches.get_achievement_summaries",
            return_value={"ach_001": {"achievement_id": "ach_001"}},
        ),
        patch(
            "backend.routers.matches.get_demand_summaries",
            return_value={"dem_001": {"demand_id": "dem_001"}},
        ),
    ):
        items = build_matches(MagicMock(), [row])

    item = items[0]

    assert item["match_id"] == row["match_id"]
    assert item["achievement_summary"]["achievement_id"] == "ach_001"
    assert item["demand_summary"]["demand_id"] == "dem_001"

    assert "risk" not in item
    assert "evidence" not in item
    assert "model" not in item


def test_b2_detail_preserves_null_risk_evidence():
    row = match_row()

    with (
        patch(
            "backend.routers.matches.get_achievement_summaries",
            return_value={"ach_001": {"achievement_id": "ach_001"}},
        ),
        patch(
            "backend.routers.matches.get_demand_summaries",
            return_value={"dem_001": {"demand_id": "dem_001"}},
        ),
    ):
        items = build_matches(
            MagicMock(), [row], detail=True
        )

    assert items[0]["risk"] is None
    assert items[0]["evidence"] is None
    assert items[0]["model"] == "b2"


def test_missing_achievement_summary_fails():
    with (
        patch(
            "backend.routers.matches.get_achievement_summaries",
            return_value={},
        ),
        patch(
            "backend.routers.matches.get_demand_summaries",
            return_value={"dem_001": {}},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            build_matches(MagicMock(), [match_row()])

    assert exc.value.status_code == 500


def test_missing_demand_summary_fails():
    with (
        patch(
            "backend.routers.matches.get_achievement_summaries",
            return_value={"ach_001": {}},
        ),
        patch(
            "backend.routers.matches.get_demand_summaries",
            return_value={},
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            build_matches(MagicMock(), [match_row()])

    assert exc.value.status_code == 500


def test_match_filter_parameters_passed_to_sql(client, db):
    exists = MagicMock()
    exists.first.return_value = (1,)

    count = MagicMock()
    count.scalar_one.return_value = 0

    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []

    db.execute.side_effect = [exists, count, rows]

    response = client.get(
        "/api/v1/demands/dem_001/matches"
        "?min_score=80&is_stale=true&page=2&page_size=5"
    )

    assert response.status_code == 200

    params = db.execute.call_args_list[1].args[1]
    assert params["min_score"] == 80
    assert params["is_stale"] is True
    assert params["object_id"] == "dem_001"

    paginated = db.execute.call_args_list[2].args[1]
    assert paginated["limit"] == 5
    assert paginated["offset"] == 5
