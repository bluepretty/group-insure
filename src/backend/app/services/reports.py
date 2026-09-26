"""Aggregate reporting over the whole platform (Stage 8).

Reporting is a read-only roll-up: ``build_report`` runs one pass over the
existing tables and returns a flat dict of counts and money totals. Nothing is
materialized to a new table — the dashboard overview cards, the Reports page,
and the JSON endpoint all render the same dict, so they always agree.

Bucket membership is defined explicitly (see below) so the numbers are easy to
explain. Money values round to 2 decimals; a nullable/None column contributes 0.0
so an empty platform returns zeros rather than raising.
"""
import datetime as dt

from sqlalchemy import select

from app.models.benefit import Benefit
from app.models.claim import Claim
from app.models.invoice import Invoice
from app.models.member import Member
from app.models.member_benefit import MemberBenefit
from app.models.party import Party
from app.models.policy import Policy


def _positive_number(value) -> float:
    """Coerce a (possibly None) numeric to a non-negative float."""
    try:
        return float(value) if value else 0.0
    except (TypeError, ValueError):
        return 0.0


def _round_money(value: float) -> float:
    return round(value, 2)


def build_report(db) -> dict:
    """Return a flat snapshot dict of the platform's counts and money totals.

    Keys (all present on every call, even an empty platform):
    - policyholders: int
    - policies: int
    - active_policies: int  (status == "active")
    - lapsed_policies: int  (status == "lapsed")
    - open_policies: int    (live policies = active + lapsed; draft/closed excluded)
    - members: int
    - active_members: int   (status == "active")
    - enrolled_premium: float  (sum of in-force elected premiums)
    - policy_premium: float    (sum of policy premiums)
    - claims_total: int
    - claims_open: int  (submitted + approved — awaiting finalization)
    - claims_paid: int
    - claims_denied: int  (rejected)
    - claims_closed: int  (finalized — paid + rejected)
    - claims_paid_total: float  (sum of amount_approved on paid claims)
    - invoiced_total: float
    - paid_total: float
    - outstanding_total: float  (invoiced_total - paid_total)
    """
    policies = db.scalars(select(Policy)).all()
    members = db.scalars(select(Member)).all()
    benefits = db.scalars(select(Benefit)).all()
    elections = db.scalars(select(MemberBenefit)).all()
    claims = db.scalars(select(Claim)).all()
    invoices = db.scalars(select(Invoice)).all()
    parties = db.scalars(select(Party)).all()

    active_policies = sum(1 for p in policies if p.status == "active")
    lapsed_policies = sum(1 for p in policies if p.status == "lapsed")
    open_policies = active_policies + lapsed_policies

    active_members = sum(1 for m in members if m.status == "active")

    enrolled_premium = sum(_positive_number(e.premium) for e in elections)
    policy_premium = sum(_positive_number(p.premium) for p in policies)

    claims_total = len(claims)
    claims_open = sum(
        1 for c in claims if c.status in ("submitted", "approved")
    )
    claims_paid = sum(1 for c in claims if c.status == "paid")
    claims_denied = sum(1 for c in claims if c.status == "rejected")
    claims_closed = sum(
        1 for c in claims if c.status in ("paid", "rejected")
    )
    claims_paid_total = sum(
        _positive_number(c.amount_approved) for c in claims if c.status == "paid"
    )

    invoiced_total = sum(_positive_number(i.total_amount) for i in invoices)
    paid_total = sum(_positive_number(i.paid_amount) for i in invoices)
    outstanding_total = invoiced_total - paid_total

    return {
        "as_of": dt.datetime.now(dt.timezone.utc),
        "policyholders": len(parties),
        "policies": len(policies),
        "active_policies": active_policies,
        "lapsed_policies": lapsed_policies,
        "open_policies": open_policies,
        "members": len(members),
        "active_members": active_members,
        "enrolled_premium": _round_money(enrolled_premium),
        "policy_premium": _round_money(policy_premium),
        "claims_total": claims_total,
        "claims_open": claims_open,
        "claims_paid": claims_paid,
        "claims_denied": claims_denied,
        "claims_closed": claims_closed,
        "claims_paid_total": _round_money(claims_paid_total),
        "invoiced_total": _round_money(invoiced_total),
        "paid_total": _round_money(paid_total),
        "outstanding_total": _round_money(outstanding_total),
    }
