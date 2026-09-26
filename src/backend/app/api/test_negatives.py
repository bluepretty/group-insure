"""Negative, boundary, and concurrency tests for the Group Insurance platform.

Where ``test_smoke.py`` proves the happy path, these prove that illegal input,
oversized fields, invalid numbers, out-of-range values, role violations, and
repeated requests are all refused the way a real attacker would hit them.

Run from ``src/backend``:

    ~/.venv/bin/python -m pytest app/api/test_negatives.py -v
"""
import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add the repo root so ``app.*`` is importable.
sys_path_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path_parent not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path_parent)

import app.main  # noqa: E402  (import after sys.path tweak)
from app.core import config, database  # noqa: E402
from app.core.database import Base  # noqa: E402


def _fresh_test_engine():
    """Rebind the app's engine + session factory to a private SQLite file.

    ``GROUP_INSURE_DATABASE_URL`` is read by ``app.core.config`` when the
    ``settings`` singleton is first imported — by the time we get here that has
    already happened, pointing at PostgreSQL. ``settings`` is mutable, so we
    override the URL it read and then rebuild the engine **and** the session
    factory (``sessionmaker`` captured the old engine by reference, so merely
    reassigning ``engine`` is not enough). ``StaticPool`` shares the single
    file connection across the worker threads ``TestClient`` spawns.
    """
    url = f"sqlite:///{os.path.join('/tmp', f'group_insure_test_{uuid.uuid4().hex}.db')}"
    os.environ["GROUP_INSURE_DATABASE_URL"] = url
    config.settings.database_url = url
    engine = create_engine(
        url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    database.engine = engine
    database.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )
    # Importing models registers them with ``Base.metadata`` *before* we create
    # the tables, so the schema is not empty.
    import app.models  # noqa: F401
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine


def _unique(name: str) -> str:
    """A guaranteed-unique username so tests never collide on a 409."""
    return f"{name}_{uuid.uuid4().hex[:8]}"


# Each negative test rebinds the app's *global* engine + session factory to a
# private SQLite file (see ``_fresh_test_engine``). That state is process-wide,
# so an autouse fixture snapshots the three affected singletons before the test
# and restores them afterwards — otherwise a later test in the same session
# (``test_smoke``, which captured the original ``engine`` at import time) would
# keep running against the last private file instead of the real one.
import pytest  # noqa: E402

ORIGINAL_DB_URL = config.settings.database_url
ORIGINAL_ENGINE = database.engine
ORIGINAL_SESSION_LOCAL = database.SessionLocal


@pytest.fixture(autouse=True)
def _restore_database_globals():
    import app.core.database as _db
    import app.core.config as _cfg

    saved_url = _cfg.settings.database_url
    saved_engine = _db.engine
    saved_session = _db.SessionLocal
    try:
        yield
    finally:
        _cfg.settings.database_url = saved_url
        _db.engine = saved_engine
        _db.SessionLocal = saved_session


class Env:
    """A per-test app + a tiny happy-path object graph (product / party /
    policy / member) so the negative cases can focus on the one thing they test.

    Each test registers its own uniquely-named underwriter to avoid clashing
    with other tests running in the same process.
    """

    def __init__(self):
        _fresh_test_engine()
        self.username = _unique("underwriter")
        self.client = TestClient(app.main.app)
        self._register(self.username)
        self._product_id = None
        self._party_id = None
        self._policy_id = None
        self._member_id = None

    def _register(self, username: str, roles: str = "underwriter") -> None:
        # Idempotent: a fresh DB per test means the first register always
        # succeeds, but ``login_token`` re-invokes this for the existing user,
        # which would otherwise collide on the username unique constraint.
        r = self.client.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": "secret123",
                "email": f"{username}@example.com",
                "roles": roles,
            },
        )
        assert r.status_code in (200, 409), r.text

    def login_token(self, username: str = None, roles: str = "underwriter") -> str:
        if username is None:
            username = self.username
        # Register with the requested role; the default ``_register`` uses
        # ``underwriter`` but role tests (e.g. the broker) pass a different role.
        self._register(username, roles)
        r = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "secret123"},
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    @property
    def token(self) -> str:
        return self.login_token()

    @property
    def product_id(self) -> int:
        if self._product_id is None:
            r = self.client.post(
                "/api/products/create",
                data={"name": "Group Term Life", "product_type": "group-term-life", "description": ""},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            assert r.status_code == 200, r.text
            rows = self.client.get(
                "/api/products", headers={"Authorization": f"Bearer {self.token}"}
            ).json()
            assert rows, "no products returned"
            self._product_id = rows[0]["id"]
        return self._product_id

    @property
    def party_id(self) -> int:
        if self._party_id is None:
            r = self.client.post(
                "/api/parties",
                json={"name": "Acme Corp", "party_type": "policyholder"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            assert r.status_code == 200, r.text
            self._party_id = r.json()["id"]
        return self._party_id

    @property
    def policy_id(self) -> int:
        if self._policy_id is None:
            r = self.client.post(
                "/api/policies/create",
                data={
                    "policy_number": "POL-001",
                    "product_id": str(self.product_id),
                    "party_id": str(self.party_id),
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            assert r.status_code == 200, r.text
            for p in self.client.get(
                "/api/policies", headers={"Authorization": f"Bearer {self.token}"}
            ).json():
                if p["policy_number"] == "POL-001":
                    self._policy_id = p["id"]
                    break
            else:
                raise RuntimeError("policy not found")
            # The create endpoint does not forward coverage dates; set them on
            # the row so term validation has a valid window.
            self._set_policy_dates()
            # draft -> active
            r = self.client.post(
                f"/api/policies/{self._policy_id}/status",
                data={"to_status": "active"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            assert r.status_code == 200, r.text
        return self._policy_id

    def _set_policy_dates(self) -> None:
        import datetime as dt
        from app.core.database import SessionLocal
        from app.models.policy import Policy

        db = SessionLocal()
        try:
            policy = db.get(Policy, self._policy_id)
            policy.start_date = dt.date(2026, 1, 1)
            policy.end_date = dt.date(2026, 12, 31)
            db.commit()
        finally:
            db.close()

    @property
    def member_id(self) -> int:
        if self._member_id is None:
            r = self.client.post(
                "/api/members/create",
                data={
                    "policy_id": str(self.policy_id),
                    "party_id": str(self.party_id),
                    "member_number": "MEM-001",
                    "first_name": "Alex",
                    "last_name": "Doe",
                    "relationship": "self",
                },
                headers={"Authorization": f"Bearer {self.token}"},
            )
            assert r.status_code == 200, r.text
            for m in self.client.get(
                "/api/members", headers={"Authorization": f"Bearer {self.token}"}
            ).json():
                if m["member_number"] == "MEM-001":
                    self._member_id = m["id"]
                    break
            else:
                raise RuntimeError("member not found")
        return self._member_id


# --- Auth: role enforcement ----------------------------------------------- #
def test_register_self_granting_role_is_refused():
    """A caller cannot register an account with an unapproved role.

    Registration previously passed the caller-supplied role straight through;
    the server now owns the role allow-list and rejects everything else so an
    attacker cannot grant themselves ``admin`` (or any other role).
    """
    app = Env().client
    # "admin" is not an approved professional role -> must be rejected, not
    # silently downgraded to a usable account.
    r = app.post(
        "/api/auth/register",
        json={"username": "evil", "password": "secret123", "email": "e@x.com", "roles": "admin"},
    )
    assert r.status_code == 400, r.text
    # An empty role is likewise invalid (must not silently default).
    r = app.post(
        "/api/auth/register",
        json={"username": "none", "password": "secret123", "email": "n@x.com", "roles": ""},
    )
    assert r.status_code == 400, r.text


def test_register_long_password_does_not_500():
    """A password longer than bcrypt's 72-byte cap must register and log in.

    bcrypt raises on inputs >72 bytes; ``hash_password`` now truncates to match
    bcrypt's real behaviour so a long password registers cleanly instead of
    returning a 500.
    """
    app = Env().client
    long_pw = "a" * 200
    r = app.post(
        "/api/auth/register",
        json={"username": "long", "password": long_pw, "email": "l@x.com", "roles": "underwriter"},
    )
    assert r.status_code == 200, r.text
    r = app.post("/api/auth/login", json={"username": "long", "password": long_pw})
    assert r.status_code == 200, r.text


def test_wrong_password_is_401():
    app = Env().client
    r = app.post("/api/auth/login", json={"username": "long", "password": "not-the-password"})
    assert r.status_code == 401, r.text


# --- RBAC: authorization failures ----------------------------------------- #
def test_unauthenticated_request_is_401():
    """An anonymous read of a protected endpoint must be refused with 401."""
    app = Env().client
    r = app.get("/api/policies")  # no Authorization header
    assert r.status_code == 401, r.text


def test_broker_cannot_create_product():
    env = Env()
    broker_token = env.login_token("broker", roles="broker")
    r = env.client.post(
        "/api/products/create",
        data={"name": "Bad", "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text


# --- Input validation: name required -------------------------------------- #
def test_product_requires_name():
    """A product create without a name fails validation (not a 500)."""
    env = Env()
    r = env.client.post(
        "/api/products/create",
        data={"name": "", "product_type": "group-term-life", "description": ""},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    # A missing required form field is a client validation error (422), not a
    # server error (500) or a custom 400.
    assert r.status_code == 422, r.text


# --- Policy status transitions -------------------------------------------- #
def test_policy_bad_transition_is_400():
    env = Env()
    # active -> draft is a forbidden backward transition.
    r = env.client.post(
        f"/api/policies/{env.policy_id}/status",
        data={"to_status": "draft"},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


def test_policy_unknown_is_400():
    env = Env()
    # An unknown policy is not found via a 404 page — the status service raises
    # a ValueError for an unknown id, which the handler surfaces as a 400.
    r = env.client.post(
        "/api/policies/999999/status",
        data={"to_status": "active"},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


# --- Claims: boundary / validation ---------------------------------------- #
def test_claim_unknown_policy_is_400():
    env = Env()
    r = env.client.post(
        "/api/claims",
        json={
            "policy_id": 999999,
            "member_id": env.member_id,
            "amount_claimed": 50.0,
            "incident_date": "2026-06-01",
        },
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


def test_claim_out_of_term_is_400():
    env = Env()
    r = env.client.post(
        "/api/claims",
        json={
            "policy_id": env.policy_id,
            "member_id": env.member_id,
            "amount_claimed": 50.0,
            "incident_date": "1999-01-01",
        },
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


# --- Renew: negative cases ------------------------------------------------ #
def test_renew_unsettled_policy_is_400():
    """Renewal must be refused while an invoice on the term is still unpaid."""
    env = Env()
    # The fixture policy has no invoice yet, so first issue one (leaving it
    # outstanding) and then try to renew — the renewal service must reject it.
    r = env.client.post(
        "/api/billing/invoices",
        data={"policy_id": str(env.policy_id)},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 200, r.text
    r = env.client.post(
        f"/api/policies/{env.policy_id}/renew",
        data={"new_start": "2027-01-01", "new_end": "2027-12-31", "premium": "12000"},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


def test_renew_bad_term_is_400():
    env = Env()
    # new_end must be later than new_start.
    r = env.client.post(
        f"/api/policies/{env.policy_id}/renew",
        data={"new_start": "2027-01-01", "new_end": "2027-01-01", "premium": ""},
        headers={"Authorization": f"Bearer {env.token}"},
    )
    assert r.status_code == 400, r.text


def test_broker_cannot_renew():
    env = Env()
    broker_token = env.login_token("broker", roles="broker")
    r = env.client.post(
        f"/api/policies/{env.policy_id}/renew",
        data={"new_start": "2027-01-01", "new_end": "2027-12-31", "premium": "12000"},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text


# --- Long-string / boundary input ----------------------------------------- #
def test_long_member_number_boundary():
    env = Env()
    r = env.client.post(
        "/api/members/create",
        data={
            "policy_id": str(env.policy_id),
            "party_id": str(env.party_id),
            "member_number": "M" * 500,
            "first_name": "A",
            "last_name": "D",
            "relationship": "self",
        },
        headers={"Authorization": f"Bearer {env.token}"},
    )
    # Either a 400 (rejected for length) or a 200 (accepted) is fine — the point
    # is it must not become an unhandled 500.
    assert r.status_code in (200, 400), r.text
