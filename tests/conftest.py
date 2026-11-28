# ============================================================
# S-11 自动化测试公共配置

# 功能说明：
# 1. 提供模拟数据库 Session、FastAPI TestClient 和测试用户身份
# 2. 统一管理依赖覆盖，避免访问真实 PostgreSQL 或 Redis
# 3. 为认证、发布、匹配查询及合作意向测试提供公共 Fixture
#
# 测试方式：pytest + MagicMock + FastAPI dependency_overrides
# 测试文件：tests/conftest.py
# ============================================================

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.database import get_db
from backend.main import app


RESEARCHER = {
    "user_id": "user_research_demo",
    "username": "research_demo",
    "role": "researcher",
    "display_name": "科研测试用户",
}

ENTERPRISE = {
    "user_id": "user_enterprise_demo",
    "username": "enterprise_demo",
    "role": "enterprise",
    "display_name": "企业测试用户",
}

OTHER_RESEARCHER = {
    "user_id": "user_other_researcher",
    "username": "other_researcher",
    "role": "researcher",
    "display_name": "其他科研用户",
}


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def client(db):
    def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def login_as():
    def set_user(user):
        app.dependency_overrides[get_current_user] = (
            lambda: dict(user)
        )

    yield set_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def researcher(client, login_as):
    login_as(RESEARCHER)
    return client


@pytest.fixture
def enterprise(client, login_as):
    login_as(ENTERPRISE)
    return client
