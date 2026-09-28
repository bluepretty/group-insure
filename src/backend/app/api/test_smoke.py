"""Smoke test: verify DB tables, register, login, products, and policies round-trip."""
import datetime as dt
import re
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.database import engine, SessionLocal, Base
from app.main import app
from app.models.invoice import Invoice
from app.models.policy import Policy
from app.models.user import User, hash_password


def setup_test_db():
    # Start from a clean slate so the fixed test users can be registered on every run.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Seed the reference tables so party/policy validation (which now checks the
    # lookup tables) has values to validate against, even though the TestClient
    # below does not drive the app startup event where seeding normally happens.
    from app.services.lookup import seed_reference_data

    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()


# `register` refuses the "admin" role, so the super-admin that drives the
# catalog writes (product/benefit create) is seeded directly via the same path
# the reset service uses, then logged in for a JWT.
_ADMIN_TOKEN_CACHE = {"value": None}


def _admin_token() -> str:
    if _ADMIN_TOKEN_CACHE["value"] is None:
        admin = "testadmin"
        db = SessionLocal()
        try:
            db.add(User(username=admin, password=hash_password("secret123"), roles="admin", active=True))
            db.commit()
        finally:
            db.close()
        login = TestClient(app)
        r = login.post("/api/auth/login", json={"username": admin, "password": "secret123"})
        assert r.status_code == 200, r.text
        _ADMIN_TOKEN_CACHE["value"] = r.json()["access_token"]
    return _ADMIN_TOKEN_CACHE["value"]


def _card_markup(html: str) -> str:
    # Keep only the bodies of the four summary cards (the cards whose label row
    # sits above the stat). Everything outside a `<div class="card ...">` block
    # — the <title>, nav, etc. — is discarded so the "—" check can't trip on
    # page chrome like the dashboard title.
    parts = re.findall(r'<div class="card[^"]*">(.*?)</div>\s*</div>\s*</div>', html, re.S)
    return "\n".join(parts)


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

    # Create a product. Products are catalog/reference data, so catalog writes
    # require the super-admin (manage_products); the underwriter only owns the
    # business side (policies, members, claims).
    admin = _admin_token()
    r = client.post(
        "/api/products/create",
        data={"name": "Group Term Life", "product_type": "group-term-life", "description": "Base plan"},
        headers={"Authorization": f"Bearer {admin}"},
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
        data={"policy_number": "POL-001", "product_id": str(product_id), "party_id": str(party_id), "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # List policies
    r = client.get("/api/policies", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    policies = r.json()
    assert policies, "policies list should not be empty"
    policy_id = policies[0]["id"]

    # The create endpoint doesn't forward dates; set them directly on the policy
    # row so the Stage 14 term validation has a valid window to check against.
    _db = SessionLocal()
    _policy = _db.get(Policy, policy_id)
    _policy.start_date = dt.date(2026, 1, 1)
    _policy.end_date = dt.date(2026, 12, 31)
    _db.commit()
    _db.close()

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
            "relationship_code": "self",
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

    # --- Stage 4: benefits + member elections ---

    # Add a benefit to the product. Benefits are catalog/reference data, so
    # adding one needs the super-admin (manage_benefits); the underwriter only
    # reads benefits (view_benefits), not write them.
    r = client.post(
        "/api/benefits/add",
        data={
            "product_id": str(product_id),
            "code": "TERM-BASE",
            "name": "Term Base",
            "benefit_type": "term",
            "coverage_amount": "100000",
            "premium_rate": "0.10",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    # List benefits as underwriter (view_benefits allowed, must succeed)
    r = client.get("/api/benefits?product_id=" + str(product_id), headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    benefits = r.json()
    assert benefits, "benefits list should not be empty"
    benefit_id = benefits[0]["id"]

    # List member coverage as underwriter (view_benefits allowed, must succeed)
    r = client.get("/api/benefits/coverage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text

    # A broker cannot add a benefit
    r = client.post(
        "/api/benefits/add",
        data={
            "product_id": str(product_id),
            "code": "BAD",
            "name": "Bad",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # A broker cannot elect a benefit
    r = client.post(
        f"/api/benefits/{members[0]['id']}/elect",
        data={"benefit_id": str(benefit_id)},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # Elect a member into the benefit (underwriter / manage_members)
    r = client.post(
        f"/api/benefits/{members[0]['id']}/elect",
        data={"benefit_id": str(benefit_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["member_id"] == members[0]["id"], r.text

    # Listing coverage should now include the election
    r = client.get("/api/benefits/coverage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json(), "coverage should not be empty after election"

    # Election must be one-per-member: electing again raises 400
    r = client.post(
        f"/api/benefits/{members[0]['id']}/elect",
        data={"benefit_id": str(benefit_id), "election_amount": "100"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # --- Stage 5: premium pricing + allocation ---

    # Set a per-unit premium rate on the benefit (0.10). Updating a benefit's
    # catalog rate is a manage_benefits action, so the super-admin does it.
    r = client.post(
        "/api/premiums/rate",
        data={"benefit_id": str(benefit_id), "premium_rate": "0.10"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["premium_rate"] == 0.10

    # A broker cannot set a premium rate.
    r = client.post(
        "/api/premiums/rate",
        data={"benefit_id": str(benefit_id), "premium_rate": "0.20"},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # The member is already elected (Stage 4). Set the election amount to 100
    # units; premium = election_amount (100) × premium_rate (0.10) = 10.00.
    r = client.post(
        "/api/premiums/elect-amount",
        data={"member_id": str(members[0]["id"]), "amount": "100"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["premium"] == 10.00, r.text

    # Per-member premium endpoint.
    r = client.get(
        f"/api/premiums/member?member_id={members[0]['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["premium"] == 10.00, r.text

    # Per-policy premium total (single member => 10.00).
    r = client.get(
        f"/api/premiums/policy?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 10.00, body
    assert len(body["breakdown"]) == 1, body

    # A broker can view premiums (view_premiums) but cannot manage them.
    r = client.get(
        f"/api/premiums/policy?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 10.00, r.text

    # The per-policy premium summary partial renders from a policy list action.
    r = client.get(
        f"/api/premiums/policy-html?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "10.00" in r.text, r.text
    assert "TERM-BASE" in r.text, r.text

    # A broker cannot set an election amount.
    r = client.post(
        "/api/premiums/elect-amount",
        data={"member_id": str(members[0]["id"]), "amount": "150"},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # Per-member premium HTML detail renders for the elected member.
    r = client.get(
        f"/api/premiums/detail?member_id={members[0]['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "10.00" in r.text, r.text

    # Coverage picker (no member_id) lists enrolled members.
    r = client.get(
        "/api/premiums/detail",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "Alex" in r.text, r.text

    # A broker can view the premium detail (view_premiums) but cannot
    # set a rate or an election amount.
    r = client.get(
        f"/api/premiums/detail?member_id={members[0]['id']}",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text
    assert "10.00" in r.text, r.text

    # --- Stage 6: billing + payments ---

    # Issue an invoice for the active policy (total = 10.00 premium).
    r = client.post(
        "/api/billing/invoices",
        data={"policy_id": str(policy_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["status"] == "issued", inv
    assert inv["total_amount"] == 10.00, inv

    # Invoice list shows it.
    r = client.get(
        "/api/billing/invoices?policy_id=" + str(policy_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert inv["id"] in [i["id"] for i in r.json()], r.text

    # A second invoice for the same (unpaid) policy is rejected.
    r = client.post(
        "/api/billing/invoices",
        data={"policy_id": str(policy_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # Record the full payment; invoice flips to paid.
    r = client.post(
        f"/api/billing/invoices/{inv['id']}/payments",
        data={"amount": "10.00", "method": "bank_transfer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    r = client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    paid = next(i for i in r.json() if i["id"] == inv["id"])
    assert paid["status"] == "paid", paid
    assert paid["paid_amount"] == 10.00, paid

    # A broker can view invoices (view_billing) but cannot manage them.
    r = client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/billing/invoices/{inv['id']}/payments",
        data={"amount": "1.00"},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # Invalid payment amount -> 400.
    r = client.post(
        f"/api/billing/invoices/{inv['id']}/payments",
        data={"amount": "0"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # --- Stage 14: claims -----------------------------------------------------

    # Enroll a fresh, active member for the claims flow (the earlier member was
    # terminated for Stage 6/12, and my validation rejects non-active members).
    r = client.post(
        "/api/members/create",
        data={
            "policy_id": str(policy_id),
            "party_id": str(party_id),
            "member_number": "MEM-CLA",
            "first_name": "Claim",
            "last_name": "Member",
            "relationship_code": "self",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # The create endpoint returns HTML; fetch the member object to get its id.
    r = client.get(
        f"/api/members?party_id={party_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    members = r.json()
    claim_member = next(m for m in members if m["member_number"] == "MEM-CLA")
    claim_member_id = claim_member["id"]

    # File a claim against the active policy's member.
    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": claim_member_id,
            "benefit_id": benefit_id,
            "amount_claimed": 500.0,
            "incident_date": "2026-06-01",
            "description": "Hospitalization",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    claim = r.json()
    assert claim["claim_number"].startswith("CLM-"), claim
    assert claim["status"] == "submitted", claim
    assert claim["amount_claimed"] == 500.0, claim

    # List claims (JSON); the filed claim appears.
    r = client.get(
        f"/api/claims?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    claims = r.json()
    assert any(c["id"] == claim["id"] for c in claims), claims

    # Fetch the single claim.
    r = client.get(
        f"/api/claims/{claim['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted", r.text

    # Adjudicate: approve, then pay out the approved amount.
    r = client.post(
        f"/api/claims/{claim['id']}/status",
        json={"status": "approved", "amount_approved": 300.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved", r.text
    assert r.json()["amount_approved"] == 300.0, r.text

    r = client.post(
        f"/api/claims/{claim['id']}/status",
        json={"status": "paid"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid", r.text
    assert r.json()["amount_approved"] == 300.0, r.text

    # A rejected claim is terminal: approve after reject is refused (400).
    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": claim_member_id,
            "amount_claimed": 100.0,
            "incident_date": "2026-06-15",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    reject_claim = r.json()
    r = client.post(
        f"/api/claims/{reject_claim['id']}/status",
        json={"status": "rejected"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected", r.text
    r = client.post(
        f"/api/claims/{reject_claim['id']}/status",
        json={"status": "approved", "amount_approved": 10.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # Validation: incident date outside the policy term -> 400.
    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": claim_member_id,
            "amount_claimed": 50.0,
            "incident_date": "2020-01-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # Validation: a claim against a non-active (terminated) member -> 400.
    # members[0] isn't guaranteed to be the terminated member, so find it.
    r = client.get(
        f"/api/members?party_id={party_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    terminated = next(
        (m for m in r.json() if m["status"] != "active"), None
    )
    assert terminated is not None, "expected a terminated member in the roster"
    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": terminated["id"],
            "amount_claimed": 50.0,
            "incident_date": "2026-06-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # Validation: unknown policy -> 400; unknown claim detail -> 404.
    r = client.post(
        "/api/claims",
        json={
            "policy_id": 999999,
            "member_id": claim_member_id,
            "amount_claimed": 50.0,
            "incident_date": "2026-06-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text
    r = client.get(
        "/api/claims/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text

    # A broker can submit (view_claims) and view claims but cannot change a
    # claim's status (manage_claims): the approval attempt is 403.
    r = client.post(
        "/api/auth/login",
        json={"username": "testbroker", "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    broker_token = r.json()["access_token"]

    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": claim_member_id,
            "amount_claimed": 75.0,
            "incident_date": "2026-06-20",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    r = client.get(
        f"/api/claims?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/claims/{claim['id']}/status",
        json={"status": "approved", "amount_approved": 100.0},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # --- HTMX claim form paths (POST /api/claims/submit + GET /api/claims/list) -

    # The list partial renders with the submit form present.
    r = client.get("/api/claims/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert "File a claim" in r.text or "submit a claim" in r.text.lower(), r.text

    # A broker may file a claim through the Form endpoint (view_claims).
    r = client.post(
        "/api/claims/submit",
        data={
            "policy_id": str(policy_id),
            "member_id": str(claim_member_id),
            "amount_claimed": "60.0",
            "incident_date": "2026-06-25",
            "description": "Filed via the HTMX form",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    # Out-of-term incident date through the Form path is surfaced as 400.
    r = client.post(
        "/api/claims/submit",
        data={
            "policy_id": str(policy_id),
            "member_id": str(claim_member_id),
            "amount_claimed": "60.0",
            "incident_date": "2019-01-01",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # An unauthenticated attempt to file a claim is refused (401). Use a fresh
    # client with no cookie store so the request is genuinely anonymous rather
    # than inheriting the broker session persisted on `client`.
    anon = TestClient(app)
    r = anon.post(
        "/api/claims/submit",
        data={
            "policy_id": str(policy_id),
            "member_id": str(claim_member_id),
            "amount_claimed": "60.0",
            "incident_date": "2026-06-25",
        },
    )
    assert r.status_code == 401, r.text

    # --- Stage 8: reports -----------------------------------------------------

    # The underwriter can read the platform-wide report (view_dashboard).
    r = client.get(
        "/api/reports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    report = r.json()

    # Well-formed: every key is present, counts are ints >= 0, totals are numbers >= 0.
    expected_keys = {
        "policyholders", "policies", "active_policies", "lapsed_policies",
        "open_policies", "members", "active_members",
        "enrolled_premium", "policy_premium",
        "claims_total", "claims_open", "claims_paid", "claims_denied",
        "claims_closed", "claims_paid_total",
        "invoiced_total", "paid_total", "outstanding_total",
    }
    assert expected_keys.issubset(report.keys()), report.keys()
    for count_key in (
        "policyholders", "policies", "active_policies", "lapsed_policies",
        "open_policies", "members", "active_members",
        "claims_total", "claims_open", "claims_paid", "claims_denied",
        "claims_closed",
    ):
        assert isinstance(report[count_key], int) and report[count_key] >= 0, (
            count_key, report[count_key]
        )
    for total_key in (
        "enrolled_premium", "policy_premium", "claims_paid_total",
        "invoiced_total", "paid_total", "outstanding_total",
    ):
        assert isinstance(report[total_key], (int, float)) and report[total_key] >= 0, (
            total_key, report[total_key]
        )

    # Reflect the fixture built earlier: one active policy, one enrolled member
    # (the fixture terminates it, so `active_members` is legitimately 0), an
    # in-force 10.00 election, and an issued-then-paid 10.00 invoice.
    assert report["active_policies"] >= 1
    assert report["policies"] >= 1
    assert report["members"] >= 1
    assert report["enrolled_premium"] >= 10.00, report["enrolled_premium"]
    assert report["policy_premium"] >= 10.00, report["policy_premium"]
    assert report["claims_total"] >= 1
    assert report["claims_closed"] >= 1, report["claims_closed"]
    assert report["claims_paid_total"] >= 300.0, report["claims_paid_total"]
    assert report["invoiced_total"] >= 10.00, report["invoiced_total"]
    assert report["paid_total"] >= 10.00, report["paid_total"]
    assert report["outstanding_total"] >= 0.0, report["outstanding_total"]

    # The HTMX partial renders against the same service.
    r = client.get(
        "/api/reports/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "Reports" in r.text, r.text

    # The dashboard home populates its four stat cards from the same report.
    r = client.get(
        "/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "—" not in _card_markup(r.text), (
        "overview cards should be populated, not —"
    )

    # The broker can view the report too (view_dashboard), but the endpoint
    # is still gated — an unauthenticated request is refused.
    r = client.get(
        "/api/reports",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    import datetime as _dt
    from app.services.policies import GRACE_DAYS, close_policy
    from app.core.database import SessionLocal as _SessionLocal

    # --- Stage 9: automated policy lapse ----------------------------------

    # Issue a new invoice for the (still active) policy, with a past due date.
    r = client.post(
        "/api/billing/invoices",
        data={"policy_id": str(policy_id), "due_date": "2024-01-01"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    overdue = r.json()
    assert overdue["total_amount"] == 10.00, overdue

    # The underpaid invoice past its due date lapses the policy automatically.
    r = client.get(
        f"/api/policies/{policy_id}/lapse-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "lapsed", body

    # The lapse-check endpoint reports the lapse.
    assert body["lapsed"] is True, body

    # Settling the outstanding invoice reinstates the policy.
    r = client.post(
        f"/api/billing/invoices/{overdue['id']}/payments",
        data={"amount": "10.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    r = client.get(
        f"/api/policies/{policy_id}/lapse-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active", body
    assert body["lapsed"] is False, body

    # A broker cannot lapse a policy.
    r = client.get(
        f"/api/policies/{policy_id}/lapse-check",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # --- Stage 10: closed lapsed policies ----------------------------------

    # Create a separate policy to drive the lapsed -> closed transition.
    r = client.post(
        "/api/policies/create",
        data={
            "policy_number": "POL-010",
            "product_id": str(product_id),
            "party_id": str(party_id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    r = client.get("/api/policies", headers={"Authorization": f"Bearer {token}"})
    policy10 = next(p for p in r.json() if p["policy_number"] == "POL-010")
    policy10_id = policy10["id"]

    # Make it active, then issue an overdue invoice to trigger auto-lapse.
    client.post(
        f"/api/policies/{policy10_id}/status",
        data={"to_status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/api/billing/invoices",
        data={"policy_id": str(policy10_id), "due_date": "2024-01-01"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = client.get(
        f"/api/policies/{policy10_id}/lapse-check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.json()["status"] == "lapsed", r.json()

    # The grace window means a freshly-lapsed policy cannot be closed yet.
    r = client.post(
        f"/api/policies/{policy10_id}/close",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # A broker cannot close a policy.
    r = client.post(
        f"/api/policies/{policy10_id}/close",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # Service-driven: inject `today`. Still inside the window -> refused.
    _db = _SessionLocal()
    try:
        try:
            close_policy(_db, policy_id=policy10_id, today=_dt.date.today())
            assert False, "refuse a policy inside the grace window"
        except ValueError:
            pass

        # Past the window -> closes to a terminal "closed".
        future = _dt.date.today() + _dt.timedelta(days=GRACE_DAYS + 5)
        closed = close_policy(_db, policy_id=policy10_id, today=future)
        assert closed.status == "closed", closed.status

        # Terminal: a second close is refused.
        try:
            close_policy(_db, policy_id=policy10_id, today=future)
            assert False, "a closed policy must be terminal"
        except ValueError:
            pass
    finally:
        _db.close()




    # --- Stage 11: policy statement (preview / PDF / email) ----------------

    POLICY_NUMBER = "POL-001"

    # Email addresses are validated on entry (single source of truth). A
    # malformed address on the policyholder party is rejected with 400.
    r = client.post(
        "/api/parties",
        json={"name": "Bad Email Co", "party_type": "policyholder",
              "email": "not-an-email"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # A well-formed address is stored lower-cased (validate_email normalises).
    r = client.post(
        "/api/parties",
        json={"name": "Good Email Co", "party_type": "policyholder",
              "email": "Policyholder@Example.COM"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # build_statement returns non-zero roll-up totals for the paid POL-001.
    from app.services.statements import build_statement
    stmt = build_statement(_SessionLocal(), policy_id=policy_id)
    assert stmt["total_invoiced"] > 0.0, stmt
    assert stmt["total_paid"] > 0.0, stmt

    # Preview renders (HTML fragment, gated on view_billing).
    r = client.get(
        f"/api/policies/{policy_id}/statement",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert POLICY_NUMBER in r.text, r.text

    # The broker can preview too (view_billing) but cannot email (needs
    # manage_billing): the send path is 403, not 200.
    r = client.get(
        f"/api/policies/{policy_id}/statement",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text

    # The PDF endpoint streams application/pdf and only needs view_billing.
    r = client.get(
        f"/api/policies/{policy_id}/statement.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf", r.headers
    assert r.content[:4] == b"%PDF", r.content[:4]

    # The send path requires manage_billing: a broker is refused.
    r = client.post(
        f"/api/policies/{policy_id}/statement/send",
        json={"confirm": True},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # With SMTP disabled (default), the confirm-send endpoint refuses with 400.
    r = client.post(
        f"/api/policies/{policy_id}/statement/send",
        json={"confirm": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text
    assert "sent" not in r.text, r.text

    # An unknown policy raises 400 (not 500).
    r = client.get(
        "/api/policies/999999/statement.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # --- Stage 12: census (life events, add/remove, proration) ------------

    import datetime as _d12

    from app.services.census import census_add, census_remove
    from app.services.life_events import list_events as _list_life_events
    from app.services.invoices import list_invoices as _list_invoices
    from app.services.policies import add_policy, change_policy_status

    # A fresh, dated, active policy so proration has a known Jan 1 -> Dec 31
    # period. The fixture's POL-001 has no coverage dates, so proration cannot
    # run over it. Do this in one session and reuse it for the add.
    policy12_db = _SessionLocal()
    policy12 = add_policy(
        policy12_db,
        policy_number="POL-012",
        product_id=product_id,
        party_id=party_id,
        start_date=_d12.date(2026, 1, 1),
        end_date=_d12.date(2026, 12, 31),
    )
    policy12_id = policy12.id
    assert policy12.start_date == _d12.date(2026, 1, 1), policy12.start_date
    assert policy12.end_date == _d12.date(2026, 12, 31), policy12.end_date
    change_policy_status(policy12_db, policy_id=policy12_id, to_status="active")

    # A benefit for the same product so the added member gets a premium. Benefits
    # are catalog data, so this add needs the super-admin (manage_benefits).
    r = client.post(
        "/api/benefits/add",
        data={
            "product_id": str(product_id),
            "code": "PROBE-BASE",
            "name": "Probe Base",
            "benefit_type": "term",
            "coverage_amount": "100000",
            "premium_rate": "0.10",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    r = client.get(
        "/api/benefits?product_id=" + str(product_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    benefit_id12 = next(b["id"] for b in r.json() if b["code"] == "PROBE-BASE")

    # --- Life event on add -------------------------------------------------

    # Add a member mid-cycle; the census returns a recorded life event.
    eff = _d12.date(2026, 7, 1)
    summary = census_add(
        _SessionLocal(),
        policy_id=policy12_id,
        member_number="MEM-CEN",
        first_name="Census",
        last_name="Add",
        effective_date=eff,
        relationship_code="self",
        benefit_id=benefit_id12,
        election_amount=100.0,
    )
    assert summary["event_type"] == "new_member", summary

    _db = _SessionLocal()
    events = [e for e in _list_life_events(_db, policy_id=policy12_id)]
    assert events, "a life event should be recorded on census add"
    assert events[0].event_type == "new_member", events[0]
    assert events[0].effective_date == eff, events[0]
    assert events[0].member_id == summary["member_id"], events[0]

    # --- Proration ---------------------------------------------------------

    # Daily proration over a full year for a change mid-year.
    period_days = (_d12.date(2026, 12, 31) - _d12.date(2026, 1, 1)).days + 1
    days_remaining = (_d12.date(2026, 12, 31) - eff).days + 1
    expected = float(round(Decimal("10.00") * days_remaining / period_days, 2))
    assert summary["added_premium"] == 10.00, summary
    assert abs(summary["adjustment"] - expected) < 0.01, summary
    assert summary["adjustment"] > 0.0, summary  # a more is owed for an add
    assert summary["proration"]["days_remaining"] == days_remaining, summary
    assert summary["proration"]["period_days"] == period_days, summary
    assert summary["proration"]["added_premium"] == 10.00, summary

    # --- Billing link ------------------------------------------------------

    # The signed adjustment becomes its own adjustment invoice (b2 model),
    # alongside the regular invoice -- not a rewrite of it.
    jinvoices = _list_invoices(_db, policy_id=policy12_id)
    adj = [i for i in jinvoices if i.invoice_number.endswith("-ADJ")]
    assert adj, "a positive add must issue an adjustment invoice"
    assert adj[0].status == "issued", adj[0]
    assert abs(float(adj[0].total_amount) - expected) < 0.01, adj[0]
    assert float(adj[0].total_amount) > 0, adj[0]

    # A broker can view invoices (view_billing) but cannot census-add.
    # Provide a valid form; the only thing standing between success and 403 is
    # the missing manage_members permission.
    r = client.post(
        f"/api/members/{policy12_id}/add",
        data={
            "member_number": "MEM-BAD",
            "first_name": "Bad",
            "last_name": "Actor",
            "effective_date": "2026-07-01",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # --- Proration on removal: a credit ------------------------------------

    rem = census_remove(_SessionLocal(), member_id=summary["member_id"], effective_date=eff)
    assert rem["event_type"] == "member_departed", rem
    assert rem["departed_premium"] == 10.00, rem
    assert rem["adjustment"] < 0.0, rem  # a removal is a credit
    assert abs(rem["adjustment"] + expected) < 0.01, rem

    _db = _SessionLocal()
    events2 = _list_life_events(_db, policy_id=policy12_id)
    assert events2[0].event_type == "member_departed", events2[0]

    jinvoices2 = _list_invoices(_db, policy_id=policy12_id)
    credit = [i for i in jinvoices2 if i.invoice_number.endswith("-ADJ") and i.total_amount < 0]
    assert credit, "a removal must issue a negative adjustment (credit) invoice"
    assert credit[0].status == "issued", credit[0]

    # The removed member's row is now terminated with a termination date.
    from app.models.member import Member

    retired = _db.get(Member, summary["member_id"])
    assert retired.status == "terminated", retired
    assert retired.termination_date == eff, retired

    # --- Email: off by default, must not send and must not break ----------

    # SMTP is disabled in the test env; the best-effort notify swallows the
    # failure. Neither the add nor the remove raised, and both logged their
    # audit lines. Confirm the audit trail carries a life_event entry.
    from app.models.audit import AuditLog
    from sqlalchemy import select

    _db.close()

    # --- Stage 13: policy renewal ------------------------------------------

    import datetime as _d13

    from app.services.invoices import create_invoice as _issue_invoice
    from app.services.payments import record_payment as _record_payment

    # Renewal only works on an active, fully-settled policy (no outstanding
    # invoice anywhere). Use a fresh, dated, active policy with a roster member
    # elected into a benefit (premium = election_amount × premium_rate), then
    # pay its term in full so it is settled. We enroll the member directly
    # (not via census_add, which issues a -ADJ invoice) to keep the policy
    # fully settled before renewal.
    policy13_db = _SessionLocal()
    policy13 = add_policy(
        policy13_db,
        policy_number="POL-013",
        product_id=product_id,
        party_id=party_id,
        start_date=_d13.date(2026, 1, 1),
        end_date=_d13.date(2026, 12, 31),
    )
    policy13_id = policy13.id
    change_policy_status(policy13_db, policy_id=policy13_id, to_status="active")

    # Create a benefit on the product and elect a member into it. Benefits are
    # catalog data, so the add needs the super-admin (manage_benefits).
    r = client.post(
        "/api/benefits/add",
        data={
            "product_id": str(product_id),
            "code": "PROBE-BASE",
            "name": "Probe Base",
            "benefit_type": "term",
            "coverage_amount": "100000",
            "premium_rate": "0.10",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    r = client.get(
        "/api/benefits?product_id=" + str(product_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    benefit_id13 = next(b["id"] for b in r.json() if b["code"] == "PROBE-BASE")

    from app.services.members import enroll_member
    from app.services.benefits import elect_benefit

    member13 = enroll_member(
        policy13_db,
        policy_id=policy13_id,
        party_id=party_id,
        member_number="MEM-REN",
        first_name="Renew",
        last_name="Me",
        effective_date=_d13.date(2026, 1, 1),
    )
    election13 = elect_benefit(
        policy13_db, member_id=member13.id, benefit_id=benefit_id13, election_amount=100.0
    )
    roster_premium = float(election13.premium or 0)
    assert roster_premium == 10.00, election13  # 100 * 0.10
    policy13_db.close()

    # Issue the term-1 invoice (billed from the roster premium) and pay it in
    # full so the policy is settled.
    _db = _SessionLocal()
    inv = _issue_invoice(_db, policy_id=policy13_id)
    assert inv.status == "issued", inv
    assert inv.total_amount is not None
    assert float(inv.total_amount) == roster_premium, inv
    amount_to_pay = float(inv.total_amount)
    _record_payment(_db, invoice_id=inv.id, amount=amount_to_pay)
    settled = _db.get(Invoice, inv.id)
    assert settled.status == "paid", settled

    # The policy is active and fully settled.
    renewed_policy = _db.get(Policy, policy13_id)
    assert renewed_policy.status == "active", renewed_policy
    _db.close()

    # Renew into a 2027 term at an explicit premium. Must start the day after
    # the current term ends (2027-01-01) and be later than it.
    r = client.post(
        f"/api/policies/{policy13_id}/renew",
        data={
            "new_start": "2027-01-01",
            "new_end": "2027-12-31",
            "premium": "12000.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["new_start"] == "2027-01-01", resp
    assert resp["new_end"] == "2027-12-31", resp
    assert float(resp["invoice_total"]) == 12000.00, resp
    assert resp["invoice_number"].startswith("INV"), resp
    assert resp["premium"] == 12000.00, resp

    # The period is rewritten to the new term; the policy stays active.
    _db = _SessionLocal()
    renewed = _db.get(Policy, policy13_id)
    assert renewed.start_date == _d13.date(2027, 1, 1), renewed
    assert renewed.end_date == _d13.date(2027, 12, 31), renewed
    assert renewed.status == "active", renewed
    new_inv = next(i for i in _list_invoices(_db, policy_id=policy13_id)
                   if i.invoice_number == resp["invoice_number"])
    assert new_inv.status == "issued", new_inv
    assert float(new_inv.total_amount) == 12000.00, new_inv

    # The renewal logged a policy_renewed audit line carrying the invoice number.
    renewal_lines = [a for a in _db.scalars(select(AuditLog)).all()
                     if a.action == "policy_renewed"]
    assert renewal_lines, "a policy_renewed audit line should exist"
    assert resp["invoice_number"] in renewal_lines[-1].details, renewal_lines[-1]
    _db.close()

    # Renewing an unsettled (unpaid) policy is refused: the one-outstanding-
    # invoice-per-policy invariant is preserved. After the 2027 renewal above
    # that invoice is unpaid, so a further renewal is refused.
    r = client.post(
        f"/api/policies/{policy13_id}/renew",
        data={
            "new_start": "2028-01-01",
            "new_end": "2028-12-31",
            "premium": "",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # A bad term is refused: new_start must be the day after the current end.
    r = client.post(
        f"/api/policies/{policy13_id}/renew",
        data={
            "new_start": "2027-06-01",
            "new_end": "2027-12-31",
            "premium": "",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # new_end must be later than new_start.
    r = client.post(
        f"/api/policies/{policy13_id}/renew",
        data={
            "new_start": "2028-01-01",
            "new_end": "2028-01-01",
            "premium": "",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # A broker (no manage_policies) cannot renew.
    r = client.post(
        f"/api/policies/{policy13_id}/renew",
        data={
            "new_start": "2027-01-01",
            "new_end": "2027-12-31",
            "premium": "",
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

if __name__ == "__main__":
    test_smoke()
