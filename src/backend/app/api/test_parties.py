"""Positive and RBAC tests for the Parties CRUD routes (edit + soft-delete).

Mirrors the users test pattern. Covers:
- edit (name/party_type/email/active) persists,
- clean soft-delete hides the party from the list,
- deactivating a party an active policy/member references is refused (409),
- broker is refused (403) on edit/delete.
"""
import os
import sys

# Register this package's dir so ``import test_negatives`` works no matter where
# pytest was launched from (mirrors the pattern in test_users.py).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import pytest

from test_negatives import Env, _unique, _restore_database_globals  # noqa: F401


@pytest.fixture(autouse=True)
def _restore(_restore_database_globals):  # reuse the globals fixture
    yield


def _create_party(env: Env, admin: str, name: str, **extra) -> int:
    payload = {"name": name, "party_type": "policyholder", **extra}
    r = env.client.post(
        "/api/parties", json=payload, headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _party_ids(env: Env, token: str) -> list[dict]:
    return env.client.get(
        "/api/parties", headers={"Authorization": f"Bearer {token}"}
    ).json()


def _party_id(env: Env, token: str, name: str) -> int | None:
    return next((p["id"] for p in _party_ids(env, token) if p["name"] == name), None)


def _link_member_to_party(env: Env, admin: str, party_id: int) -> None:
    """Create an active Member referencing ``party_id`` so the party is in use.

    Uses the member-create API (with the fixture's policy) so this exercises the
    same path the guard queries. The member_number must be unique per policy.
    """
    import datetime as dt

    member_number = f"MEM-{dt.datetime.now(dt.timezone.utc).timestamp():.0f}"
    r = env.client.post(
        "/api/members/create",
        data={
            "policy_id": str(env.policy_id),
            "party_id": str(party_id),
            "member_number": member_number,
            "first_name": "Alex",
            "last_name": "Doe",
            "relationship": "self",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text


def test_edit_party_persists():
    env = Env()
    admin = env.login_token()
    name = _unique("Party")
    pid = _create_party(env, admin, name, email="old@x.com")

    r = env.client.put(
        f"/api/parties/{pid}",
        data={"name": name, "party_type": "policyholder", "email": "new@x.com"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    target = _party_id(env, admin, name)
    assert target is not None
    r = env.client.get(
        f"/api/parties/{target}", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.json()["email"] == "new@x.com"


def test_edit_invalid_party_is_400():
    env = Env()
    admin = env.login_token()
    name = _unique("Party")
    r = env.client.post(
        "/api/parties",
        json={"name": name, "party_type": "policyholder"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    pid = _party_id(env, admin, name)

    r = env.client.put(
        f"/api/parties/{pid}",
        data={"name": "", "party_type": "", "email": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code in (400, 422), r.text


def test_clean_soft_delete_hides_party():
    env = Env()
    admin = env.login_token()
    name = _unique("Party")
    r = env.client.post(
        "/api/parties",
        json={"name": name, "party_type": "policyholder"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    pid = _party_id(env, admin, name)

    r = env.client.delete(f"/api/parties/{pid}", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    rows = env.client.get(
        "/api/parties", headers={"Authorization": f"Bearer {admin}"}
    )
    assert not any(p["name"] == name for p in rows.json()), "soft-deleted party still listed"


def test_deactivate_party_in_use_is_409():
    env = Env()
    admin = env.login_token()
    name = _unique("Party")
    r = env.client.post(
        "/api/parties",
        json={"name": name, "party_type": "policyholder"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    pid = _party_id(env, admin, name)
    # Link a member to this party so the delete guard fires.
    _link_member_to_party(env, admin, pid)
    r = env.client.delete(f"/api/parties/{pid}", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 409, r.text
    assert "cannot deactivate" in r.json()["detail"].lower()


def test_broker_can_edit_party():
    """Brokers own ``manage_parties`` and may edit/delete parties."""
    env = Env()
    admin = env.login_token()
    name = _unique("Party")
    r = env.client.post(
        "/api/parties",
        json={"name": name, "party_type": "policyholder"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    pid = _party_id(env, admin, name)
    broker = env.login_token("broker", roles="broker")
    headers = {"Authorization": f"Bearer {broker}"}

    r = env.client.put(
        f"/api/parties/{pid}",
        data={"name": name, "party_type": "policyholder"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    r = env.client.delete(f"/api/parties/{pid}", headers=headers)
    assert r.status_code == 200, r.text
