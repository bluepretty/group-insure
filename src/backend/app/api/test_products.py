"""Positive and RBAC tests for the Products CRUD routes (edit + soft-delete).

Mirrors the users test pattern. Covers:
- edit (name/product_type/description/is_active) persists,
- clean soft-delete hides the product from the list,
- deactivating a product an active policy references is refused (409),
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


def _product_id(env: Env, token: str, name: str) -> int:
    rows = env.client.get(
        "/api/products", headers={"Authorization": f"Bearer {token}"}
    ).json()
    for r in rows:
        if r["name"] == name:
            return r["id"]
    raise RuntimeError(f"product {name!r} not found")


def test_edit_product_persists():
    env = Env()
    admin = env._admin_token()
    name = _unique("Product")
    # Create a product.
    r = env.client.post(
        "/api/products/create",
        data={"name": name, "product_type": "group-term-life", "description": "orig"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    pid = _product_id(env, admin, name)

    # Edit it.
    r = env.client.put(
        f"/api/products/{pid}",
        data={"name": name, "product_type": "group-health", "description": "edited"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    rows = env.client.get(
        "/api/products", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    target = next(r for r in rows if r["name"] == name)
    assert target["product_type"] == "group-health"
    assert target["description"] == "edited"


def test_edit_invalid_product_is_400():
    env = Env()
    admin = env._admin_token()
    name = _unique("Product")
    env.client.post(
        "/api/products/create",
        data={"name": name, "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    pid = _product_id(env, admin, name)
    # Missing required fields (name/product_type are required Form fields) → 422.
    r = env.client.put(
        f"/api/products/{pid}",
        data={"name": "", "product_type": "", "description": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code in (400, 422), r.text


def test_clean_soft_delete_hides_product():
    env = Env()
    admin = env._admin_token()
    name = _unique("Product")
    env.client.post(
        "/api/products/create",
        data={"name": name, "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    pid = _product_id(env, admin, name)

    r = env.client.delete(f"/api/products/{pid}", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    rows = env.client.get(
        "/api/products", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    assert not any(r["name"] == name for r in rows), "soft-deleted product still listed"


def test_deactivate_product_in_use_is_409():
    env = Env()
    admin = env._admin_token()
    name = _unique("Product")
    env.client.post(
        "/api/products/create",
        data={"name": name, "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    pid = _product_id(env, admin, name)
    # Create a policy referencing this product.
    env.party_id
    r = env.client.post(
        "/api/policies/create",
        data={"policy_number": "POL-TEST", "product_id": str(pid), "party_id": str(env.party_id)},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    r = env.client.delete(f"/api/products/{pid}", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 409, r.text
    assert "cannot deactivate" in r.json()["detail"].lower()


def test_broker_cannot_edit_or_delete_product():
    env = Env()
    admin = env._admin_token()
    name = _unique("Product")
    env.client.post(
        "/api/products/create",
        data={"name": name, "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    pid = _product_id(env, admin, name)
    broker = env.login_token("broker", roles="broker")
    headers = {"Authorization": f"Bearer {broker}"}

    r = env.client.put(
        f"/api/products/{pid}",
        data={"name": name, "product_type": "group-health", "description": ""},
        headers=headers,
    )
    assert r.status_code == 403, r.text
    r = env.client.delete(f"/api/products/{pid}", headers=headers)
    assert r.status_code == 403, r.text
