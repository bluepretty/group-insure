"""Positive and RBAC tests for the Members CRUD routes (edit + in-use remove).

Mirrors the parties/users test pattern. Covers:
- edit (first/last/relationship) persists and is re-read via GET /{id},
- clean remove (no in-use rows) terminates the member,
- removing a member with an open claim or a benefit election is refused (409),
- broker is refused (403) on the manage-gated edit/remove routes.
"""
import os
import sys

# Register this package's dir so ``import test_negatives`` works no matter where
# pytest was launched from (mirrors the pattern in test_negatives.py).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import pytest

from test_negatives import Env, _unique, _restore_database_globals  # noqa: F401


@pytest.fixture(autouse=True)
def _restore(_restore_database_globals):  # reuse the globals fixture
    yield


def _create_member(
    env: Env,
    admin: str,
    member_number: str | None = None,
    first_name: str = "Alex",
    last_name: str = "Doe",
    relationship: str = "self",
) -> int:
    member_number = member_number or f"MEM-{_unique('n')}"
    r = env.client.post(
        "/api/members/create",
        data={
            "policy_id": str(env.policy_id),
            "party_id": str(env.party_id),
            "member_number": member_number,
            "first_name": first_name,
            "last_name": last_name,
            "relationship": relationship,
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    rows = env.client.get(
        "/api/members", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    target = next(
        (m for m in rows if m["member_number"] == member_number), None
    )
    assert target is not None, f"member {member_number} not found in list"
    return target["id"]


def _member(env: Env, token: str, member_number: str) -> dict:
    rows = env.client.get(
        "/api/members", headers={"Authorization": f"Bearer {token}"}
    ).json()
    return next(m for m in rows if m["member_number"] == member_number)


def test_edit_member_persists():
    env = Env()
    admin = env.login_token()
    mn = f"MEM-{_unique('n')}"
    mid = _create_member(env, admin, member_number=mn)

    r = env.client.put(
        f"/api/members/{mid}",
        data={"first_name": "Alicia", "last_name": "Changed", "relationship": "spouse"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["first_name"] == "Alicia"

    target = _member(env, admin, mn)
    assert target["first_name"] == "Alicia"
    assert target["last_name"] == "Changed"
    assert target["relationship"] == "spouse"


def test_edit_member_unknown_is_404():
    env = Env()
    admin = env.login_token()
    r = env.client.put(
        "/api/members/999999",
        data={"first_name": "X", "last_name": "Y", "relationship": ""},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 404, r.text


def test_get_member_unknown_is_404():
    env = Env()
    admin = env.login_token()
    r = env.client.get(
        "/api/members/999999", headers={"Authorization": f"Bearer {admin}"}
    )
    assert r.status_code == 404, r.text


def test_clean_remove_terminates_member():
    env = Env()
    admin = env.login_token()
    mn = f"MEM-{_unique('n')}"
    mid = _create_member(env, admin, member_number=mn)

    # census_remove prorates a credit, so issue a fully-settled (paid) invoice
    # for the policy first to avoid a proration failure mid-test.
    from app.core.database import SessionLocal
    from app.models.invoice import Invoice
    from app.models.policy import Policy

    db = SessionLocal()
    try:
        policy = db.get(Policy, env.policy_id)
        if policy.premium is None:
            policy.premium = 1000.0
        invoice = Invoice(
            policy_id=policy.id,
            invoice_number=f"INV-{_unique('inv')}",
            status="paid",
            total_amount=1000.0,
            paid_amount=1000.0,
        )
        db.add(invoice)
        db.commit()
    finally:
        db.close()

    r = env.client.post(
        f"/api/members/{mid}/remove",
        data={"effective_date": "2026-06-01"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 200, r.text

    target = _member(env, admin, mn)
    assert target["status"] == "terminated"


def test_remove_member_with_claim_is_409():
    env = Env()
    admin = env.login_token()
    from app.core.database import SessionLocal
    from app.models.claim import Claim
    from app.models.member import Member
    from app.models.policy import Policy
    import datetime as dt

    db = SessionLocal()
    try:
        policy = db.get(Policy, env.policy_id)
        member = Member(
            policy_id=policy.id,
            party_id=env.party_id,
            member_number=f"MEM-claim-{_unique('n')}",
            first_name="Lit",
            last_name="igant",
            relationship="self",
        )
        db.add(member)
        db.flush()
        claim = Claim(
            claim_number=f"CLM-{_unique('c')}",
            policy_id=policy.id,
            member_id=member.id,
            incident_date=dt.date(2026, 1, 1),
            amount_claimed=500.0,
            status="submitted",
        )
        db.add(claim)
        db.commit()
        mid = member.id
    finally:
        db.close()

    r = env.client.post(
        f"/api/members/{mid}/remove",
        data={"effective_date": "2026-06-01"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 409, r.text
    assert "remove" in r.json()["detail"].lower()


def test_remove_member_with_election_is_409():
    env = Env()
    admin = env.login_token()
    import datetime as dt

    from app.core.database import SessionLocal
    from app.models.benefit import Benefit
    from app.models.member import Member
    from app.models.member_benefit import MemberBenefit
    from app.models.policy import Policy
    from app.models.product import Product

    db = SessionLocal()
    try:
        policy = db.get(Policy, env.policy_id)
        product = Product(name=f"Prod-{_unique('p')}", product_type="group-term-life")
        db.add(product)
        db.flush()
        benefit = Benefit(
            product_id=product.id, code=f"BEN-{_unique('b')}", name="Base"
        )
        db.add(benefit)
        db.flush()
        member = Member(
            policy_id=policy.id,
            party_id=env.party_id,
            member_number=f"MEM-elec-{_unique('n')}",
            first_name="E",
            last_name="lectee",
            relationship="self",
        )
        db.add(member)
        db.flush()
        election = MemberBenefit(member_id=member.id, benefit_id=benefit.id)
        db.add(election)
        db.commit()
        mid = member.id
    finally:
        db.close()

    r = env.client.post(
        f"/api/members/{mid}/remove",
        data={"effective_date": "2026-06-01"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 409, r.text
    assert "remove" in r.json()["detail"].lower()


def test_broker_cannot_edit_or_remove_member():
    env = Env()
    admin = env.login_token()
    mn = f"MEM-{_unique('n')}"
    mid = _create_member(env, admin, member_number=mn)

    broker = env.login_token("broker2", roles="broker")
    headers = {"Authorization": f"Bearer {broker}"}

    r = env.client.put(
        f"/api/members/{mid}",
        data={"first_name": "Nope", "last_name": "Doe", "relationship": ""},
        headers=headers,
    )
    assert r.status_code == 403, r.text

    r = env.client.post(
        f"/api/members/{mid}/remove",
        data={"effective_date": "2026-06-01"},
        headers=headers,
    )
    assert r.status_code == 403, r.text

    # The member must be untouched after the refused calls.
    target = _member(env, admin, mn)
    assert target["first_name"] == "Alex"
