"""Mid-term proration of policy premiums for census changes (Stage 12).

A group policy's roster is never static — members are added or removed
mid-cycle. The policy premium is a live sum of its members' premiums, so every
census change alters what the policyholder owes for the *remaining* policy
period.

Proration uses **daily proration over the policy period**:

    adjustment = annual_premium × (days_remaining / period_days)

``period_days`` is the full policy length and ``days_remaining`` counts from the
change's ``effective_date`` through ``end_date`` inclusive, so the member is
billed for the full days coverage actually ran. ``annual_premium`` is signed:
positive for an added member (more owed), negative for a departed member (a
credit). The adjustment is then billed/credited as a separate
adjustment invoice (see ``services/invoices.py::issue_adjustment_invoice``).
"""
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from app.models.policy import Policy
from app.services.audit import record_log
from app.services.premiums import refresh_policy_premium


def _round(amount: Decimal) -> float:
    """Round to two decimal places (policy currency's minor unit)."""
    quant = Decimal("0.01")
    return float(Decimal(str(amount)).quantize(quant, rounding=ROUND_HALF_UP))


def _get_policy(db, policy_id: int):
    """Fetch a policy by id (the shared accessor used by this module)."""
    return db.get(Policy, policy_id)


def compute_proration(
    *,
    start_date: dt.date,
    end_date: dt.date,
    effective_date: dt.date,
    annual_premium: float,
) -> dict:
    """Daily-prorate an annual premium over the remaining policy period.

    ``days_remaining`` counts the days from ``effective_date`` through
    ``end_date`` inclusive; ``period_days`` is the full policy length (from
    ``start_date`` through ``end_date`` inclusive). ``annual_premium`` may be
    negative (a departure credit). Returns the signed prorated amount plus the
    counts that produced it.
    """
    if effective_date > end_date:
        raise ValueError("effective_date cannot be after the policy end date")
    period_days = (end_date - start_date).days + 1
    days_remaining = (end_date - effective_date).days + 1
    amount = _round(Decimal(str(annual_premium)) * Decimal(days_remaining) / Decimal(period_days))
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "effective_date": effective_date.isoformat(),
        "days_remaining": days_remaining,
        "period_days": period_days,
        "annual_premium": float(annual_premium),
        "amount": amount,
    }


def prorate_policy(
    db,
    *,
    policy_id: int,
    effective_date: dt.date,
    added_premium: float = 0.0,
    departed_premium: float = 0.0,
) -> dict:
    """Translate a census change into a prorated premium adjustment.

    Re-computes and persists the policy's whole-year premium for the new roster
    (via ``refresh_policy_premium``), records the ``policy_premium_adjusted``
    audit line, and returns the prorated signed adjustment for the *remaining*
    period plus the supporting counts.

    ``added_premium`` is the added member's annual premium (for a census add);
    ``departed_premium`` is the departed member's annual premium (for a
    removal, credited as a negative adjustment). One of them should be set;
    both zero is a no-op adjustment.
    """
    policy = _get_policy(db, policy_id)
    if policy is None or policy.start_date is None or policy.end_date is None:
        raise ValueError(
            f"Policy {policy_id} has no start/end date; cannot prorate over the "
            "policy period"
        )
    if policy.status != "active":
        raise ValueError(
            f"Policy {policy_id} is not active (is '{policy.status}'); census "
            "proration requires an active policy"
        )

    # Re-compute and persist the whole-year premium for the new roster so the
    # policy's premium reflects the change immediately.
    refresh_policy_premium(db, policy_id=policy_id)

    net = added_premium - departed_premium
    proration = compute_proration(
        start_date=policy.start_date,
        end_date=policy.end_date,
        effective_date=effective_date,
        annual_premium=net,
    )

    record_log(
        db,
        action="policy_premium_adjusted",
        entity="Policy",
        entity_id=policy_id,
        details=(
            f"added_premium={added_premium} departed_premium={departed_premium} "
            f"net={round(net, 2)} adjustment={proration['amount']}"
        ),
    )

    return {
        "policy_id": policy_id,
        "start_date": policy.start_date.isoformat(),
        "end_date": policy.end_date.isoformat(),
        "effective_date": effective_date.isoformat(),
        "days_remaining": proration["days_remaining"],
        "period_days": proration["period_days"],
        "added_premium": added_premium,
        "departed_premium": departed_premium,
        "net_annual": round(net, 2),
        "new_premium": float(policy.premium or 0.0),
        "adjustment": proration["amount"],
    }
