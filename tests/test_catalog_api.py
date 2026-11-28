# ============================================================
# 成果、需求、标签与标签体系查询测试

# 功能说明：
# 1. 验证成果与需求的数据字段转换及敏感信息保护
# 2. 验证分页、TRL 边界、发布状态及 mine 权限
# 3. 验证不存在的资源和无标签资源的响应
# 4. 验证 taxonomy 维度、枚举代码及中文标签
#
# 测试方式：pytest + TestClient + MagicMock（只模拟数据库）
# 测试文件：tests/test_catalog_api.py
# ============================================================

from datetime import date

from unittest.mock import MagicMock, patch

import pytest

from backend.routers.achievements import to_achievement
from backend.routers.demands import to_demand
from backend.routers.taxonomy import DIMENSIONS


def achievement_row():
    return {
        "achievement_id": "ach_001",
        "title_original": "Battery Research",
        "abstract_original": "A" * 400,
        "capability_profile_zh": None,
        "publication_year": 2025,
        "type": "article",
        "source": "openalex",
        "source_url": "https://openalex.org/W123",
        "language": "en",
        "trl": None,
        "tech_fields": [{"code": "electrolyte", "is_primary": True}],
        "application_scenarios": [],
        "is_simulated": False,
        "dataset_version": "v0.1.2",
        "publisher_user_id": None,
        "published_at": None,
        "doi": None,
        "venue": None,
        "keywords": None,
        "topics": None,
        "clean_status": "cleaned",
        "review_status": "pending",
        "trl_evidence": None,
        "key_metrics": None,
        "material_system": None,
        "process": None,
        "ip_status": "unknown",
    }


def demand_row():
    return {
        "demand_id": "dem_001",
        "enterprise_id": "ent_001",
        "title": "Battery Demand",
        "pain_point": "Battery degradation",
        "expected_solution": "Improve cycle life",
        "technical_metrics": None,
        "budget_range": None,
        "timeline": None,
        "cooperation_modes": None,
        "required_trl": 5,
        "tech_fields": ["electrolyte"],
        "application_scenarios": ["ev_power"],
        "ip_requirement": None,
        "region": "any",
        "status": "active",
        "valid_until": date(2027, 12, 31),
        "is_simulated": True,
        "source_note": "Test data",
        "dataset_version": "v0.1.2",
        "publisher_user_id": None,
        "published_at": None,
        "enterprise_display_name": "模拟企业",
        "enterprise_industry": "battery_manufacturing",
        "enterprise_size": "medium",
    }


def test_achievement_preview_truncation():
    result = to_achievement(achievement_row())

    assert len(result["abstract_preview"]) == 300
    assert result["abstract_preview"].endswith("…")
    assert "abstract_original" not in result


def test_achievement_unknown_trl_stays_null():
    result = to_achievement(achievement_row())

    assert result["trl"] is None
    assert result["capability_profile_zh"] is None
    assert result["application_scenarios"] == []


def test_achievement_detail_has_original_abstract():
    result = to_achievement(achievement_row(), detail=True)

    assert len(result["abstract_original"]) == 400
    assert result["trl_evidence"] is None
    assert result["keywords"] == []
    assert result["key_metrics"] == []


def test_demand_enterprise_privacy():
    result = to_demand(demand_row(), detail=True)

    assert result["enterprise"]["display_name"] == "模拟企业"
    assert "legal_name" not in result["enterprise"]
    assert "enterprise_display_name" not in result


def test_demand_summary_omits_detail_fields():
    result = to_demand(demand_row())

    assert result["demand_id"] == "dem_001"
    assert result["is_simulated"] is True
    assert "expected_solution" not in result
    assert "technical_metrics" not in result


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/achievements?page=0",
        "/api/v1/achievements?page_size=101",
        "/api/v1/achievements?trl_min=0",
        "/api/v1/achievements?trl_max=10",
        "/api/v1/demands?required_trl=0",
        "/api/v1/demands?required_trl=10",
        "/api/v1/demands?publication_status=invalid",
    ],
)
def test_invalid_catalog_filters(client, endpoint):
    assert client.get(endpoint).status_code == 422


def test_invalid_trl_range(client):
    response = client.get(
        "/api/v1/achievements?trl_min=8&trl_max=2"
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/achievements/does_not_exist",
        "/api/v1/demands/does_not_exist",
    ],
)
def test_missing_catalog_detail_returns_404(
    client, db, endpoint
):
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = client.get(endpoint)

    assert response.status_code == 404


def test_empty_achievement_list(client, db):
    count = MagicMock()
    count.scalar_one.return_value = 0

    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []

    db.execute.side_effect = [count, rows]

    response = client.get("/api/v1/achievements?page=1&page_size=5")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert response.json()["data"]["pagination"]["total"] == 0


def test_empty_demand_list(client, db):
    count = MagicMock()
    count.scalar_one.return_value = 0

    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []

    db.execute.side_effect = [count, rows]

    response = client.get("/api/v1/demands")

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/achievements?publication_status=mine",
        "/api/v1/demands?publication_status=mine",
    ],
)
def test_mine_filter_requires_auth(client, endpoint):
    assert client.get(endpoint).status_code == 401


def test_achievement_mine_filter(researcher, db):
    count = MagicMock()
    count.scalar_one.return_value = 0
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count, rows]

    with patch(
        "backend.routers.achievements.get_current_user",
        return_value={"user_id": "user_research_demo", "role": "researcher"},
    ):
        response = researcher.get(
            "/api/v1/achievements?publication_status=mine"
        )

    assert response.status_code == 200
    params = db.execute.call_args_list[0].args[1]
    assert params["user_id"] == "user_research_demo"


def test_demand_mine_filter(enterprise, db):
    count = MagicMock()
    count.scalar_one.return_value = 0
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count, rows]

    with patch(
        "backend.routers.demands.get_current_user",
        return_value={"user_id": "user_enterprise_demo", "role": "enterprise"},
    ):
        response = enterprise.get(
            "/api/v1/demands?publication_status=mine"
        )

    assert response.status_code == 200
    params = db.execute.call_args_list[0].args[1]
    assert params["user_id"] == "user_enterprise_demo"


def test_taxonomy_contains_all_11_dimensions(client):
    response = client.get("/api/v1/taxonomy")

    assert response.status_code == 200
    dimensions = response.json()["data"]["dimensions"]

    assert len(dimensions) == 11
    assert len({d["dimension"] for d in dimensions}) == 11


def test_taxonomy_tech_field(client):
    response = client.get(
        "/api/v1/taxonomy?dimension=tech_field"
    )

    assert response.status_code == 200

    dimensions = response.json()["data"]["dimensions"]
    assert len(dimensions) == 1
    assert dimensions[0]["dimension"] == "tech_field"
    assert len(dimensions[0]["values"]) == 8


def test_taxonomy_unknown_dimension(client):
    response = client.get(
        "/api/v1/taxonomy?dimension=unknown"
    )

    assert response.status_code == 400


def test_taxonomy_all_values_have_labels():
    for dimension in DIMENSIONS:
        assert dimension["values"]

        for value in dimension["values"]:
            assert value["code"]
            assert value["label"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/achievements/unknown/tags",
        "/api/v1/demands/unknown/tags",
    ],
)
def test_missing_parent_tags_404(client, db, endpoint):
    db.execute.return_value.first.return_value = None

    assert client.get(endpoint).status_code == 404


@pytest.mark.parametrize(
    "endpoint,parent",
    [
        ("/api/v1/achievements/ach_001/tags", "achievement_id"),
        ("/api/v1/demands/dem_001/tags", "demand_id"),
    ],
)
def test_existing_parent_without_tags(
    client, db, endpoint, parent
):
    exists = MagicMock()
    exists.first.return_value = (1,)

    tags = MagicMock()
    tags.mappings.return_value.all.return_value = []

    db.execute.side_effect = [exists, tags]

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json()["data"]["tags"] == []
    assert parent in response.json()["data"]
