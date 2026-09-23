"""Smoke test: verify DB tables, register, login, products, and policies round-trip."""
from fastapi.testclient import TestClient

from app.core.database import engine, SessionLocal, Base
from app.main import app
from app.models.user import User


def setup_test_db():
    # Start from a clean slate so the fixed test users can be registered on every run.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_smoke():
    setup_test_db()
    client = TestClient(app)

    # Health
    r = client.get("/health")
    assert r.status_code == 200, r.text

    # Register an underwriter (can manage products + policies)
    r = client.post(
        "/api/auth/register",
        json={"username": "testunderwriter", "password": "secret123", "email": "u@example.com", "roles": "underwriter"},
    )
    assert r.status_code == 200, r.text

    # Register a broker (cannot manage products/policies)
    r = client.post(
        "/api/auth/register",
        json={"username": "testbroker", "password": "secret123", "email": "b@example.com", "roles": "broker"},
    )
    assert r.status_code == 200, r.text

    # Login
    r = client.post("/api/auth/login", json={"username": "testunderwriter", "password": "secret123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token

    # /me with token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "testunderwriter"

    # Bad login
    r = client.post("/api/auth/login", json={"username": "testunderwriter", "password": "wrong"})
    assert r.status_code == 401

    # Create a product
    r = client.post(
        "/api/products/create",
        data={"name": "Group Term Life", "product_type": "group-term-life", "description": "Base plan"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # Fetch the product to get its id
    r = client.get("/api/products", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    products = r.json()
    assert products, "products list should not be empty"
    product_id = products[0]["id"]

    # Create a policyholder party (needed as policy target)
    r = client.post(
        "/api/parties",
        json={"name": "Acme Corp", "party_type": "policyholder"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    party_id = r.json()["id"]

    # Create a policy
    r = client.post(
        "/api/policies/create",
        data={"policy_number": "POL-001", "product_id": str(product_id), "party_id": str(party_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # List policies
    r = client.get("/api/policies", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    policies = r.json()
    assert policies, "policies list should not be empty"
    policy_id = policies[0]["id"]

    # Change policy status draft -> active
    r = client.post(
        f"/api/policies/{policy_id}/status",
        data={"to_status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # Invalid transition should return 400
    # A policy cannot move from active back to draft (no backward transitions).
    r = client.post(
        f"/api/policies/{policy_id}/status",
        data={"to_status": "draft"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # Enroll a member on the policy
    r = client.post(
        "/api/members/create",
        data={
            "policy_id": str(policy_id),
            "party_id": str(party_id),
            "member_number": "MEM-001",
            "first_name": "Alex",
            "last_name": "Doe",
            "relationship": "self",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # List members as underwriter (should be viewable, and we can see it)
    r = client.get("/api/members?party_id=" + str(party_id), headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    members = r.json()
    assert members, "members list should not be empty"

    # List members as broker (view_members allowed, must succeed)
    r = client.post("/api/auth/login", json={"username": "testbroker", "password": "secret123"})
    assert r.status_code == 200, r.text
    broker_token = r.json()["access_token"]
    r = client.get(
        "/api/members?party_id=" + str(party_id),
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    # A broker cannot enroll a member
    r = client.post(
        "/api/members/create",
        data={
            "policy_id": str(policy_id),
            "member_number": "MEM-BAD",
            "first_name": "Bad",
            "last_name": "Actor",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # Terminate the member; confirm the API reflects the change
    r = client.post(
        f"/api/members/{members[0]['id']}/terminate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "terminated", r.text

    # A broker cannot terminate a member either
    r = client.post(
        f"/api/members/{members[0]['id']}/terminate",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # A broker cannot create a product
    r = client.post("/api/auth/login", json={"username": "testbroker", "password": "secret123"})
    broker_token = r.json()["access_token"]
    r = client.post(
        "/api/products/create",
        data={"name": "Bad", "product_type": "group-health"},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    print("\nALL SMOKE TESTS PASSED ✓")


if __name__ == "__main__":
    test_smoke()
