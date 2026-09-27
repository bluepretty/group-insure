"""Aggregate reporting over the whole platform (Stage 8).

Reporting is a read-only roll-up: ``build_report`` runs a handful of
column-level aggregate queries (``COUNT``, ``SUM`` over ``CASE`` buckets) and
returns a flat dict of counts and money totals. Nothing is materialized to a
new table — the dashboard overview cards, the Reports page, and the JSON
endpoint all render the same dict, so they always agree.

Aggregating in SQL rather than loading every row and counting in Python means
the endpoint cost is O(1) query work, not proportional to table size. Bucket
membership is defined explicitly (see below) so the numbers are easy to
explain. Money values round to 2 decimals; a nullable/None column contributes
0.0 so an empty platform returns zeros rather than raising.
"""
import datetime as dt

from sqlalchemy import Case, func, select

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
    # Each aggregate is a single column-level query rather than a full-table
    # row load. The multi-column selects are executed with ``db.execute(...).one()``
    # (a Session exposes no ``.one()`` of its own) and the rows unpack as tuples.
    # ``func.count()`` is an int; ``func.sum()`` over a column with no
    # non-null rows yields NULL in SQLite, so wrap every SUM in COALESCE(.., 0)
    # to keep these non-None. The tuples are coerced to int for the report
    # contract (counts are always int).
    (
        policies,
        active_policies,
        lapsed_policies,
    ) = db.execute(
        select(
            func.count(Policy.id),
            func.coalesce(
                func.sum(Case((Policy.status == "active", 1)), else_=0), 0
            ),
            func.coalesce(
                func.sum(Case((Policy.status == "lapsed", 1)), else_=0), 0
            ),
        )
    ).one()
    policies = int(policies)
    active_policies = int(active_policies)
    lapsed_policies = int(lapsed_policies)
    open_policies = active_policies + lapsed_policies

    (members, active_members) = db.execute(
        select(
            func.count(Member.id),
            func.coalesce(
                func.sum(Case((Member.status == "active", 1)), else_=0), 0
            ),
        )
    ).one()
    members = int(members)
    active_members = int(active_members)

    (
        claims_total,
        claims_open,
        claims_paid,
        claims_denied,
    ) = db.execute(
        select(
            func.count(Claim.id),
            func.coalesce(
                func.sum(
                    Case(
                        ((Claim.status.in_(("submitted", "approved"))), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(Case((Claim.status == "paid", 1)), else_=0), 0
            ),
            func.coalesce(
                func.sum(Case((Claim.status == "rejected", 1)), else_=0), 0
            ),
        )
    ).one()
    (
        claims_total,
        claims_open,
        claims_paid,
        claims_denied,
    ) = (
        int(claims_total),
        int(claims_open),
        int(claims_paid),
        int(claims_denied),
    )
    claims_closed = claims_paid + claims_denied
    claims_paid_total = float(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        Case(
                            ((Claim.status == "paid", Claim.amount_approved)),
                            else_=0,
                        )
                    ),
                    0,
                )
            )
        )
    )

    invoiced_total = float(
        db.scalar(
            select(func.coalesce(func.sum(Invoice.total_amount), 0.0))
        )
    )
    paid_total = float(
        db.scalar(
            select(func.coalesce(func.sum(Invoice.paid_amount), 0.0))
        )
    )
    outstanding_total = invoiced_total - paid_total

    enrolled_premium = float(
        db.scalar(
            select(func.coalesce(func.sum(MemberBenefit.premium), 0.0))
        )
    )
    policy_premium = float(
        db.scalar(
            select(func.coalesce(func.sum(Policy.premium), 0.0))
        )
    )

    policyholders = int(
        db.scalar(select(func.count(Party.id)))
    )

    return {
        "as_of": dt.datetime.now(dt.timezone.utc),
        "policyholders": policyholders,
        "policies": policies,
        "active_policies": active_policies,
        "lapsed_policies": lapsed_policies,
        "open_policies": open_policies,
        "members": members,
        "active_members": active_members,
        "enrolled_premium": _round_money(enrolled_premium),
        "policy_premium": _round_money(policy_premium),
        "claims_total": claims_total,
        "claims_open": claims_open,
        "claims_paid": claims_paid,
        "claims_denied": claims_denied,
        "claims_closed": claims_closed,
        "claims_paid_total": _round_money(claims_paid_total or 0.0),
        "invoiced_total": _round_money(invoiced_total or 0.0),
        "paid_total": _round_money(paid_total or 0.0),
        "outstanding_total": _round_money(outstanding_total or 0.0),
    }
