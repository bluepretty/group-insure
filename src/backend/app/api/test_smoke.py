"""Smoke test: verify DB tables, register, and login round-trip."""
from fastapi.testclient import TestClient

from app.core.database import engine, SessionLocal, Base
from app.main import app
from app.models.user import User


def setup_test_db():
    Base.metadata.create_all(bind=engine)


def test_smoke():
    setup_test_db()
    client = TestClient(app)

    # Health
    r = client.get("/health")
    assert r.status_code == 200, r.text

    # Register
    r = client.post(
        "/api/auth/register",
        json={"username": "testbroker", "password": "secret123", "email": "b@example.com", "roles": "broker"},
    )
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    assert uid is not None

    # Login
    r = client.post("/api/auth/login", json={"username": "testbroker", "password": "secret123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token

    # /me with token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "testbroker"

    # Bad login
    r = client.post("/api/auth/login", json={"username": "testbroker", "password": "wrong"})
    assert r.status_code == 401

    print("\nALL SMOKE TESTS PASSED ✓")


if __name__ == "__main__":
    test_smoke()
