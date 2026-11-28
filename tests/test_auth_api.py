# ============================================================
# 用户身份认证与角色权限测试

# 功能说明：
# 1. 验证 PBKDF2-SHA256 密码哈希校验
# 2. 验证 JWT 签发、有效期及无效 Token 拒绝
# 3. 验证登录成功、错误密码、未知账号和当前用户查询
# 4. 验证 researcher 与 enterprise 发布权限隔离
#
# 测试方式：pytest + TestClient + MagicMock（不使用真实密码）
# 测试文件：tests/test_auth_api.py
# ============================================================

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from backend.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    create_access_token,
    verify_password,
)
from tests.conftest import RESEARCHER

def make_hash(password):
    import hashlib

    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        260000,
    )

    return (
        f"pbkdf2_sha256$260000$"
        f"{salt.hex()}${digest.hex()}"
    )


def test_password_correct():
    assert verify_password("test-password", make_hash("test-password"))


def test_password_wrong():
    assert not verify_password("wrong", make_hash("test-password"))


@pytest.mark.parametrize(
    "stored",
    ["", "invalid", "sha256$100$a$b", None],
)
def test_invalid_password_hash(stored):
    assert not verify_password("password", stored)


def test_jwt_subject():
    token = create_access_token(RESEARCHER["user_id"])
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
    )

    assert payload["sub"] == RESEARCHER["user_id"]


def test_jwt_expiration():
    token = create_access_token(RESEARCHER["user_id"])
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
    )

    expiry = datetime.fromtimestamp(
        payload["exp"],
        timezone.utc,
    )

    remaining = expiry - datetime.now(timezone.utc)

    assert timedelta(hours=1, minutes=59) <= remaining
    assert remaining <= timedelta(hours=2)


def test_login_success(client, db):
    db.execute.return_value.mappings.return_value.first.return_value = {
        **RESEARCHER,
        "password_hash": make_hash("password123"),
    }

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "research_demo",
            "password": "password123",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["user"]["role"] == "researcher"
    assert isinstance(data["token"], str)


def test_login_wrong_password(client, db):
    db.execute.return_value.mappings.return_value.first.return_value = {
        **RESEARCHER,
        "password_hash": make_hash("correct"),
    }

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "research_demo",
            "password": "wrong",
        },
    )

    assert response.status_code == 401


def test_login_unknown_user(client, db):
    db.execute.return_value.mappings.return_value.first.return_value = None

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "unknown", "password": "wrong"},
    )

    assert response.status_code == 401


def test_me_without_token(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_me_valid_token(client):
    token = create_access_token(RESEARCHER["user_id"])

    with patch(
        "backend.auth.find_user",
        return_value=RESEARCHER,
    ):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "researcher"


def test_expired_token(client):
    token = jwt.encode(
        {
            "sub": RESEARCHER["user_id"],
            "exp": datetime.now(timezone.utc)
            - timedelta(seconds=10),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_invalid_token(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401


def test_researcher_cannot_publish_demand(researcher):
    response = researcher.post(
        "/api/v1/demands",
        json={"demand_id": "dem_001", "updates": {}},
    )

    assert response.status_code == 403


def test_enterprise_cannot_publish_achievement(enterprise):
    response = enterprise.post(
        "/api/v1/achievements",
        json={"achievement_id": "ach_001", "updates": {}},
    )

    assert response.status_code == 403
