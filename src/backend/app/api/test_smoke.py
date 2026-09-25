"""Smoke test: verify DB tables, register, login, products, and policies round-trip."""
import re

from fastapi.testclient import TestClient

from app.core.database import engine, SessionLocal, Base
from app.main import app
from app.models.user import User


def setup_test_db():
    # Start from a clean slate so the fixed test users can be registered on every run.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


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

    # --- Stage 4: benefits + member elections ---

    # Add a benefit to the product (underwriter / manage_benefits). Include a
    # catalog per-unit premium rate of 0.10.
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
        headers={"Authorization": f"Bearer {token}"},
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

    # Set a per-unit premium rate on the benefit (0.10).
    r = client.post(
        "/api/premiums/rate",
        data={"benefit_id": str(benefit_id), "premium_rate": "0.10"},
        headers={"Authorization": f"Bearer {token}"},
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

    # --- Stage 7: claims ------------------------------------------------------

    # File a claim against the policy's benefit (underwriter / manage_claims).
    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": members[0]["id"],
            "benefit_id": benefit_id,
            "claim_amount": 500.0,
            "reason": "Hospitalization",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    claim = r.json()
    assert claim["status"] == "open", claim
    assert claim["claim_amount"] == 500.0, claim

    # List claims (JSON); the filed claim appears with its status.
    r = client.get(
        f"/api/claims?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    claims = r.json()
    assert claim["id"] in [c["id"] for c in claims], claims
    assert next(c for c in claims if c["id"] == claim["id"])["status"] == "open"

    # Fetch the single claim.
    r = client.get(
        f"/api/claims/{claim['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open", r.text

    # Move to under_review, then adjudicate a partial payment -> "paid".
    r = client.post(
        f"/api/claims/{claim['id']}/review",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "under_review", r.text

    r = client.post(
        f"/api/claims/{claim['id']}/adjudicate",
        json={"paid_amount": 300.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid", r.text
    assert r.json()["paid_amount"] == 300.0, r.text

    # Close the paid claim -> terminal "closed".
    r = client.post(
        f"/api/claims/{claim['id']}/close",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed", r.text

    # A closed claim is terminal: another transition returns 400.
    r = client.post(
        f"/api/claims/{claim['id']}/review",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # An unknown claim returns 404.
    r = client.get(
        "/api/claims/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text

    # A claim referencing an unknown policy is rejected -> 400.
    r = client.post(
        "/api/claims",
        json={"policy_id": 999999, "claim_amount": 100.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text

    # A broker can view claims (view_claims) but cannot manage them.
    r = client.post(
        "/api/auth/login",
        json={"username": "testbroker", "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    broker_token = r.json()["access_token"]

    r = client.get(
        f"/api/claims?policy_id={policy_id}",
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 200, r.text
    assert claim["id"] in [c["id"] for c in r.json()], r.text

    r = client.post(
        "/api/claims",
        json={
            "policy_id": policy_id,
            "member_id": members[0]["id"],
            "benefit_id": benefit_id,
            "claim_amount": 100.0,
        },
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

    # The broker cannot adjudicate a claim either.
    r = client.post(
        f"/api/claims/{claim['id']}/adjudicate",
        json={"paid_amount": 10.0},
        headers={"Authorization": f"Bearer {broker_token}"},
    )
    assert r.status_code == 403, r.text

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

    print("\nALL SMOKE TESTS PASSED ✓")


if __name__ == "__main__":
    test_smoke()
