# ============================================================
# API 路由与数据契约测试

# 功能说明：
# 1. 验证 v0.1.2 版本及必需 API 路由和 HTTP 方法
# 2. 检查合作意向、联系人、标签、匹配任务的响应模型
# 3. 检查分页参数、状态枚举与统一校验错误结构
# 4. 验证非法请求参数返回 HTTP 422
#
# 测试方式：pytest + OpenAPI + TestClient（模拟数据库）
# 测试文件：tests/test_api_contract.py
# ============================================================

import pytest

from backend.main import app


PATHS = {
    "/health": ["get"],
    "/api/v1/auth/login": ["post"],
    "/api/v1/auth/me": ["get"],
    "/api/v1/achievements": ["get", "post"],
    "/api/v1/achievements/{achievement_id}": ["get"],
    "/api/v1/demands": ["get", "post"],
    "/api/v1/demands/{demand_id}": ["get"],
    "/api/v1/taxonomy": ["get"],
    "/api/v1/achievements/{achievement_id}/tags": ["get"],
    "/api/v1/demands/{demand_id}/tags": ["get"],
    "/api/v1/achievements/{achievement_id}/matches": ["get"],
    "/api/v1/demands/{demand_id}/matches": ["get"],
    "/api/v1/matches/{match_id}": ["get"],
    "/api/v1/pipeline-runs/{run_id}": ["get"],
    "/api/v1/pipeline-runs/{run_id}/retry": ["post"],
    "/api/v1/intents": ["get", "post"],
    "/api/v1/intents/{intent_id}/confirm": ["post"],
    "/api/v1/intents/{intent_id}/decline": ["post"],
    "/api/v1/intents/{intent_id}/contact": ["get"],
}


@pytest.mark.parametrize(
    "path,methods",
    list(PATHS.items()),
)
def test_required_routes(path, methods):
    paths = app.openapi()["paths"]

    assert path in paths

    for method in methods:
        assert method in paths[path]


def test_api_version():
    assert app.version == "0.1.2"


def test_retry_returns_202():
    operation = app.openapi()["paths"][
        "/api/v1/pipeline-runs/{run_id}/retry"
    ]["post"]

    assert "202" in operation["responses"]


def test_intent_response_schema():
    fields = app.openapi()["components"]["schemas"][
        "IntentData"
    ]["properties"]

    expected = {
        "intent_id",
        "achievement_id",
        "demand_id",
        "match_id",
        "initiator_user_id",
        "status",
        "contact_revealed",
        "achievement_title",
        "demand_title",
        "created_at",
        "updated_at",
    }

    assert expected <= set(fields)


def test_contact_response_schema():
    schemas = app.openapi()["components"]["schemas"]
    fields = schemas["ContactData"]["properties"]

    assert {
        "researcher_contact",
        "enterprise_contact",
        "is_simulated",
    } <= set(fields)

    assert not {"email", "phone", "is_mock"} & set(fields)

    person = schemas["ContactInfo"]["properties"]
    assert {"name", "email", "phone"} <= set(person)


def test_tag_parent_fields():
    fields = app.openapi()["components"]["schemas"][
        "TagItem"
    ]["properties"]

    assert "achievement_id" in fields
    assert "demand_id" in fields


def test_pipeline_status_enum():
    schemas = app.openapi()["components"]["schemas"]
    status = schemas["PipelineRunData"]["properties"]["status"]

    assert set(status["enum"]) == {
        "running",
        "success",
        "partial",
        "failed",
    }


def test_retry_response_fields():
    fields = app.openapi()["components"]["schemas"][
        "PipelineRetryData"
    ]["properties"]

    assert {"run_id", "dispatch_status"} <= set(fields)


def test_intent_list_filters():
    operation = app.openapi()["paths"][
        "/api/v1/intents"
    ]["get"]

    names = {p["name"] for p in operation["parameters"]}

    assert {
        "achievement_id",
        "demand_id",
        "status",
        "page",
        "page_size",
    } <= names


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/achievements",
        "/api/v1/demands",
        "/api/v1/intents",
    ],
)
def test_pagination_parameters(path):
    operation = app.openapi()["paths"][path]["get"]
    names = {p["name"] for p in operation["parameters"]}

    assert {"page", "page_size"} <= names


def test_validation_error_schema():
    schema = app.openapi()["components"]["schemas"][
        "APIValidationError"
    ]

    assert set(schema["required"]) == {
        "code",
        "message",
        "data",
    }


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/achievements?page=0",
        "/api/v1/demands?page_size=101",
        "/api/v1/intents?page=-1",
        "/api/v1/achievements/ach_001/matches?min_score=101",
        "/api/v1/demands/dem_001/matches?min_score=-1",
    ],
)
def test_invalid_query_returns_422(client, login_as, url):
    from tests.conftest import RESEARCHER

    login_as(RESEARCHER)
    response = client.get(url)

    assert response.status_code == 422
    assert response.json()["code"] == 42201
    assert response.json()["data"] is None


def test_invalid_publish_request_returns_422(researcher):
    response = researcher.post(
        "/api/v1/achievements",
        json={"achievement_id": ""},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42201


def test_unknown_endpoint_returns_404(client):
    response = client.get("/api/v1/nonexistent-endpoint")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
