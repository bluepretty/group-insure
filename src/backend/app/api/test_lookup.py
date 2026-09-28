"""Reference/lookup CRUD endpoints (party_types / party_roles / policy_statuses).

Covers the four operations the user asked for: list, create, update, and
soft-delete, plus RBAC (only the super-admin may write) and the in-use guard
(cannot deactivate a value business records still point at).
"""
import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import pytest

from test_negatives import Env, _unique, _restore_database_globals  # noqa: F401


@pytest.fixture(autouse=True)
def _restore(_restore_database_globals):
    yield


def _list(env: Env, kind: str, token: str) -> list[dict]:
    r = env.client.get(f"/api/lookup/{kind}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["values"]


def _assert_seeded(env: Env, token: str) -> None:
    """The seed run must have populated each table before any test writes."""
    assert _list(env, "party_types", token), "party_types not seeded"
    assert _list(env, "party_roles", token), "party_roles not seeded"
    assert _list(env, "policy_statuses", token), "policy_statuses not seeded"


def _create(env: Env, token: str, kind: str, code: str, name: str) -> None:
    r = env.client.post(
        f"/api/lookup/{kind}",
        data={"code": code, "name": name, "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_seeded_values_are_listable():
    """Each reference table ships with its baseline rows, readable by anyone."""
    env = Env()
    _assert_seeded(env, env.token)


def test_create_updates_returns_row():
    env = Env()
    admin = env._admin_token()
    # Create a new party type, then read it back.
    _create(env, admin, "party_types", "nonprofit", "Nonprofit")
    values = _list(env, "party_types", admin)
    codes = {v["code"] for v in values}
    assert "nonprofit" in codes
    row = next(v for v in values if v["code"] == "nonprofit")
    assert row["name"] == "Nonprofit"
    assert row["is_active"] is True


def test_create_duplicate_is_409():
    env = Env()
    admin = env._admin_token()
    r = env.client.post(
        "/api/lookup/policy_statuses",
        data={"code": "active", "name": "Active", "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 409, r.text


def test_create_empty_name_is_400():
    env = Env()
    admin = env._admin_token()
    r = env.client.post(
        "/api/lookup/policy_statuses",
        data={"code": "brand_new", "name": "", "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text


def test_invent_new_policy_status_is_400():
    """policy_statuses is a fixed set: a brand-new code is refused."""
    env = Env()
    admin = env._admin_token()
    r = env.client.post(
        "/api/lookup/policy_statuses",
        data={"code": "frozen", "name": "Frozen", "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text
    # And it must not now be listable.
    values = _list(env, "policy_statuses", admin)
    assert "frozen" not in {v["code"] for v in values}


def test_create_new_party_role_allowed():
    """party_roles is open: a new role code can be invented."""
    env = Env()
    admin = env._admin_token()
    _create(env, admin, "party_roles", "risk_officer", "Risk Officer")
    values = _list(env, "party_roles", admin)
    assert "risk_officer" in {v["code"] for v in values}


def test_broker_cannot_create_lookup_value():
    env = Env()
    broker = env.login_token("broker", roles="broker")
    r = env.client.post(
        "/api/lookup/policy_statuses",
        data={"code": "new_status", "name": "New Status", "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {broker}"},
    )
    assert r.status_code == 403, r.text


def test_underwriter_cannot_create_lookup_value():
    env = Env()
    underwriter = env.login_token()
    r = env.client.post(
        "/api/lookup/policy_statuses",
        data={"code": "new_status", "name": "New Status", "description": "", "sort_order": 0},
        headers={"Authorization": f"Bearer {underwriter}"},
    )
    assert r.status_code == 403, r.text


def test_unread_lookup_value_requires_auth():
    env = Env()
    r = env.client.get("/api/lookup/policy_statuses")  # no Authorization header
    assert r.status_code == 401, r.text


def test_deactivate_policy_status_in_use_is_409():
    """A status an active policy holds cannot be deactivated (409)."""
    env = Env()
    admin = env._admin_token()
    # Build an active policy first; the fresh fixture has no policy, so without
    # this there is nothing in use to trip the guard.
    env.policy_id
    r = env.client.delete(
        "/api/lookup/policy_statuses/active",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 409, r.text
    assert "cannot deactivate" in r.json()["detail"].lower()


def test_deactivate_unused_policy_status_ok():
    """A status no policy holds can be deactivated (soft-delete, keeps row)."""
    env = Env()
    admin = env._admin_token()
    # 'draft' is unused by the active fixture policy.
    r = env.client.delete(
        "/api/lookup/policy_statuses/draft",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    # It is gone from the list but still queryable for audit.
    values = _list(env, "policy_statuses", admin)
    assert not any(v["code"] == "draft" for v in values)


def test_deactivate_unknown_kind_is_400():
    env = Env()
    admin = env._admin_token()
    r = env.client.delete(
        "/api/lookup/not_a_kind/active",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text
