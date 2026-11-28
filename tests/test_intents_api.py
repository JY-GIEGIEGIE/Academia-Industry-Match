# ============================================================
# 合作意向生命周期与联系人权限测试

# 功能说明：
# 1. 验证创建意向、重复意向和双方发布条件
# 2. 验证参与者与发起人的操作权限
# 3. 验证确认、拒绝及非法状态变更
# 4. 验证确认后才可获取双方模拟联系人
# 5. 验证合作意向列表筛选与分页
#
# 测试方式：pytest + TestClient + MagicMock（不写入真实意向）
# 测试文件：tests/test_intents_api.py
# ============================================================

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import ENTERPRISE, OTHER_RESEARCHER, RESEARCHER

NOW = datetime(2026, 11, 28, tzinfo=timezone.utc)


def pair():
    return {
        "achievement_id": "ach_001",
        "demand_id": "dem_001",
        "achievement_title": "Battery Research",
        "demand_title": "Battery Demand",
        "researcher_id": RESEARCHER["user_id"],
        "enterprise_id": ENTERPRISE["user_id"],
    }


def intent_row(status="expressed", initiator=None):
    initiator = initiator or RESEARCHER["user_id"]

    return {
        "intent_id": "intent_001",
        "achievement_id": "ach_001",
        "demand_id": "dem_001",
        "initiator_user_id": initiator,
        "status": status,
        "contact_revealed": status == "confirmed",
        "achievement_title": "Battery Research",
        "demand_title": "Battery Demand",
        "researcher_id": RESEARCHER["user_id"],
        "enterprise_id": ENTERPRISE["user_id"],
        "created_at": NOW,
        "updated_at": NOW,
    }


def body():
    return {
        "achievement_id": "ach_001",
        "demand_id": "dem_001",
    }


def test_create_missing_pair_returns_404(researcher):
    with patch(
        "backend.routers.intents.get_pair",
        return_value=None,
    ):
        response = researcher.post(
            "/api/v1/intents", json=body()
        )

    assert response.status_code == 404


def test_nonparticipant_cannot_create(client, login_as):
    login_as(OTHER_RESEARCHER)

    with patch(
        "backend.routers.intents.get_pair",
        return_value=pair(),
    ):
        response = client.post(
            "/api/v1/intents", json=body()
        )

    assert response.status_code == 403


def test_both_sides_must_be_published(researcher):
    p = pair()
    p["enterprise_id"] = None

    with patch(
        "backend.routers.intents.get_pair",
        return_value=p,
    ):
        response = researcher.post(
            "/api/v1/intents", json=body()
        )

    assert response.status_code == 409


def test_duplicate_intent_returns_409(researcher, db):
    db.execute.return_value.scalar_one_or_none.return_value = (
        "intent_existing"
    )

    with patch(
        "backend.routers.intents.get_pair",
        return_value=pair(),
    ):
        response = researcher.post(
            "/api/v1/intents", json=body()
        )

    assert response.status_code == 409


def test_create_success(researcher, db):
    db.execute.return_value.scalar_one_or_none.return_value = None

    with (
        patch(
            "backend.routers.intents.get_pair",
            return_value=pair(),
        ),
        patch(
            "backend.routers.intents.get_intent",
            return_value=intent_row(),
        ),
        patch(
            "backend.routers.intents.latest_match_id",
            return_value=None,
        ),
    ):
        response = researcher.post(
            "/api/v1/intents", json=body()
        )

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "expressed"
    assert response.json()["data"]["contact_revealed"] is False

    db.commit.assert_called_once()


def test_initiator_cannot_confirm(researcher):
    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(),
    ):
        response = researcher.post(
            "/api/v1/intents/intent_001/confirm"
        )

    assert response.status_code == 403


def test_initiator_cannot_decline(researcher):
    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(),
    ):
        response = researcher.post(
            "/api/v1/intents/intent_001/decline"
        )

    assert response.status_code == 403


def test_nonparticipant_cannot_confirm(client, login_as):
    login_as(OTHER_RESEARCHER)

    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(),
    ):
        response = client.post(
            "/api/v1/intents/intent_001/confirm"
        )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "action,new_status,contact_revealed",
    [
        ("confirm", "confirmed", True),
        ("decline", "declined", False),
    ],
)
def test_status_transitions(
    enterprise, db, action, new_status, contact_revealed
):
    with (
        patch(
            "backend.routers.intents.get_intent",
            side_effect=[
                intent_row(status="expressed"),
                intent_row(status=new_status),
            ],
        ),
        patch(
            "backend.routers.intents.latest_match_id",
            return_value=None,
        ),
    ):
        response = enterprise.post(
            f"/api/v1/intents/intent_001/{action}"
        )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["status"] == new_status
    assert data["contact_revealed"] is contact_revealed

    db.commit.assert_called_once()

    params = db.execute.call_args.args[1]
    assert params["new_status"] == new_status
    assert params["contact_revealed"] is contact_revealed


@pytest.mark.parametrize("status", ["confirmed", "declined", "closed"])
def test_invalid_status_transition_returns_409(
    enterprise, status
):
    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(status=status),
    ):
        response = enterprise.post(
            "/api/v1/intents/intent_001/confirm"
        )

    assert response.status_code == 409


def test_contact_requires_confirmation(researcher):
    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(status="expressed"),
    ):
        response = researcher.get(
            "/api/v1/intents/intent_001/contact"
        )

    assert response.status_code == 403


def test_nonparticipant_cannot_get_contacts(client, login_as):
    login_as(OTHER_RESEARCHER)

    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(status="confirmed"),
    ):
        response = client.get(
            "/api/v1/intents/intent_001/contact"
        )

    assert response.status_code == 403


@pytest.mark.parametrize("user", [RESEARCHER, ENTERPRISE])
def test_confirmed_contacts_are_simulated(
    client, login_as, user
):
    login_as(user)

    with patch(
        "backend.routers.intents.get_intent",
        return_value=intent_row(status="confirmed"),
    ):
        response = client.get(
            "/api/v1/intents/intent_001/contact"
        )

    assert response.status_code == 200

    data = response.json()["data"]

    assert data["is_simulated"] is True
    assert data["status"] == "confirmed"

    for key in ("researcher_contact", "enterprise_contact"):
        assert {"name", "email", "phone"} <= set(data[key])
        assert data[key]["email"].endswith(".invalid")

    assert "is_mock" not in data
    assert "email" not in data
    assert "phone" not in data


def test_intent_list_filters(researcher, db):
    count = MagicMock()
    count.scalar_one.return_value = 0

    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []

    db.execute.side_effect = [count, rows]

    response = researcher.get(
        "/api/v1/intents"
        "?status=expressed"
        "&achievement_id=ach_001"
        "&demand_id=dem_001"
        "&page=2&page_size=5"
    )

    assert response.status_code == 200

    params = db.execute.call_args_list[0].args[1]

    assert params["status"] == "expressed"
    assert params["achievement_id"] == "ach_001"
    assert params["demand_id"] == "dem_001"
    assert params["user_id"] == RESEARCHER["user_id"]

    page_params = db.execute.call_args_list[1].args[1]
    assert page_params["limit"] == 5
    assert page_params["offset"] == 5


def test_invalid_intent_status(researcher):
    response = researcher.get(
        "/api/v1/intents?status=invalid"
    )
    assert response.status_code == 422


def test_intent_requires_authentication(client):
    response = client.get("/api/v1/intents")
    assert response.status_code == 401
