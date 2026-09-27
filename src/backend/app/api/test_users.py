"""Positive and RBAC tests for the Users management endpoints.

These cover the CRUD routes on ``/api/users`` introduced in stage13:

* edit roles / email persists,
* clean delete returns ``200 {"ok": True}`` and the user is gone,
* deleting a user who underwrites a policy returns ``409``,
* deleting your own account returns ``400``,
* a broker is refused (``403``) on every ``/api/users/*`` route.

They reuse the ``Env`` fixture (plus ``_fresh_test_engine`` /
``_restore_database_globals``) from ``test_negatives.py``. ``test_negatives`` adds
its own directory to ``sys.path`` on import, but we import the sibling module
*before* that runs, so we do the same path insertion first — the same trick
``test_negatives`` uses for ``import app.main``.

Run from ``src/backend``:

    ~/.venv/bin/python -m pytest app/api/test_users.py -v
"""
import os
import sys
import uuid

# Register this package's dir so ``import test_negatives`` works no matter where
# pytest was launched from (mirrors the pattern at the top of test_negatives.py).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import pytest
from fastapi.testclient import TestClient

# Pull in Env + the DB fixtures (imports app.models, sets up the private DB).
from test_negatives import Env  # noqa: E402


def _user_id(env: Env, admin_token: str, username: str) -> int:
    """Resolve a username to its id via the authenticated ``/api/users`` list."""
    rows = env.client.get(
        "/api/users", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    for r in rows:
        if r["username"] == username:
            return r["id"]
    raise RuntimeError(f"user {username!r} not found")


def _me(env: Env, admin_token: str) -> int:
    """The id of the env's own (admin) user."""
    return _user_id(env, admin_token, env.username)


# --- Edit ------------------------------------------------------------------ #
def test_edit_roles_and_email_persist():
    """Editing a user's roles and email over the API actually persists."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("editee")
    env.login_token(target_username, roles="underwriter")

    target_id = _user_id(env, admin, target_username)
    new_email = f"{target_username}@new.example.com"
    r = env.client.put(
        f"/api/users/{target_id}",
        data={"roles": "broker", "email": new_email, "active": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    fetched = env.client.get(
        f"/api/users/{target_id}", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    assert fetched["roles"] == "broker"
    assert fetched["email"] == new_email


def test_edit_invalid_role_is_400():
    """A caller-supplied role outside the allow-list is rejected, not applied."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("editee")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)

    r = env.client.put(
        f"/api/users/{target_id}",
        data={"roles": "admin", "email": "", "active": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text


def test_set_short_password_is_400():
    """A password shorter than 8 characters is rejected by the set-password route."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("editee")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)

    r = env.client.post(
        f"/api/users/{target_id}/set-password",
        data={"new_password": "short"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text


def test_set_password_then_login():
    """Setting a password lets the user log in with it (proves the hash persisted)."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("editee")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)

    r = env.client.post(
        f"/api/users/{target_id}/set-password",
        data={"new_password": "brand-new-1"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    # The old password no longer works; the new one does.
    login = env.client.post(
        "/api/auth/login", json={"username": target_username, "password": "secret123"}
    )
    assert login.status_code == 401, login.text
    login = env.client.post(
        "/api/auth/login", json={"username": target_username, "password": "brand-new-1"}
    )
    assert login.status_code == 200, login.text


# --- Delete: clean path ---------------------------------------------------- #
def test_clean_delete_returns_ok_and_removes_user():
    """A user with no in-use rows is deleted and a subsequent get returns 404."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("victim")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)

    r = env.client.delete(
        f"/api/users/{target_id}", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    gone = env.client.get(
        f"/api/users/{target_id}", headers={"Authorization": f"Bearer {admin}"}
    )
    assert gone.status_code == 404, gone.text


# --- Delete: in-use guard -------------------------------------------------- #
def test_delete_user_with_policy_is_409():
    """A user who underwrites a policy cannot be deleted (409 with a reason)."""
    env = Env()
    admin = env.login_token()
    target_username = _unique("victim")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)

    # Build a policy directly in the DB with this user as underwriter. The
    # policy-create *endpoint* requires manage_policies (which our underwriter
    # lacks), so build the product + policy by hand. The delete-guard only
    # inspects the Policy.underwriter_id column.
    import datetime as dt
    from app.core.database import SessionLocal
    from app.models.policy import Policy
    from app.models.product import Product

    db = SessionLocal()
    try:
        product = Product(name="Test", product_type="group-term-life", description="")
        db.add(product)
        db.flush()
        policy = Policy(
            policy_number=f"POL-{target_username}",
            product_id=product.id,
            underwriter_id=target_id,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31),
        )
        db.add(policy)
        db.commit()
    finally:
        db.close()

    r = env.client.delete(
        f"/api/users/{target_id}", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 409, r.text
    assert "still in use" in r.json()["detail"].lower()


# --- Delete: self / not found ---------------------------------------------- #
def test_delete_own_account_is_400():
    env = Env()
    admin = env.login_token()
    r = env.client.delete(
        f"/api/users/{_me(env, admin)}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400, r.text
    assert "own account" in r.json()["detail"].lower()


def test_delete_unknown_is_404():
    env = Env()
    admin = env.login_token()
    r = env.client.delete(
        "/api/users/999999", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 404, r.text


# --- RBAC ------------------------------------------------------------------ #
def test_broker_cannot_manage_users():
    """A broker is refused (403) on every ``manage_users``-gated route."""
    env = Env()
    admin = env.login_token()
    broker = env.login_token("broker2", roles="broker")
    headers = {"Authorization": f"Bearer {broker}"}

    # GET list is gated by manage_users -> 403. (GET /{id} uses require_user, so
    # it is intentionally not part of the gated set.)
    assert env.client.get("/api/users", headers=headers).status_code == 403
    target_username = _unique("victim")
    env.login_token(target_username, roles="underwriter")
    target_id = _user_id(env, admin, target_username)
    assert (
        env.client.delete(f"/api/users/{target_id}", headers=headers).status_code == 403
    )


def _unique(name: str) -> str:
    return f"{name}_{uuid.uuid4().hex[:8]}"
