"""Census orchestration (Stage 12): mid-term add/remove with proration.

A census change is a *combined* operation: it (a) changes the roster, (b)
records a LifeEvent, (c) recomputes the policy premium, (d) prorates the change
over the remaining policy period, (e) issues a separate adjustment invoice for
the signed delta, and (f) optionally emails the policyholder. This module ties
those pieces together into one call so the API layer and the smoke test drive a
census atomically.

The billing effect follows the "(b2)" census model: the original invoice stands
and a *separate* signed adjustment invoice is issued for the mid-term delta
(``services/invoices.py::issue_adjustment_invoice``), which is exempt from the
one-outstanding-invoice-per-policy invariant.
"""
import datetime as dt

from app.core.database import SessionLocal
from app.models.member import Member
from app.models.policy import Policy
from app.services import emails
from app.services.life_events import record_event
from app.services.members import enroll_member, terminate_member
from app.services.premiums import per_member_premium, refresh_policy_premium
from app.services.proration import prorate_policy


def _add_effect(
    db,
    *,
    policy_id: int,
    member_number: str,
    first_name: str,
    last_name: str,
    effective_date: dt.date,
    relationship: str | None,
    benefit_id: int | None,
    election_amount: float | None,
    actor_id: int | None,
) -> tuple[Member, float]:
    """Enroll a new member mid-term and return the member + their annual premium.

    The member's premium is ``election_amount × premium_rate`` when an election is
    set for the change; otherwise 0 (unbilled). Raises on the usual service
    ``ValueError`` (unknown policy, duplicate member number).
    """
    member = enroll_member(
        db,
        policy_id=policy_id,
        member_number=member_number,
        first_name=first_name,
        last_name=last_name,
        relationship=relationship or None,
        effective_date=effective_date,
    )
    premium = 0.0
    if benefit_id is not None and election_amount is not None:
        from app.services.benefits import elect_benefit  # local: avoid cycle

        elect_benefit(db, member_id=member.id, benefit_id=benefit_id,
                      election_amount=election_amount)
        premium = float(per_member_premium(db, member_id=member.id) or 0)
    return member, premium


def census_add(
    db,
    *,
    policy_id: int,
    member_number: str,
    first_name: str,
    last_name: str,
    effective_date: dt.date,
    relationship: str | None = None,
    benefit_id: int | None = None,
    election_amount: float | None = None,
    actor_id: int | None = None,
) -> dict:
    """Add a member (or dependent) mid-policy-cycle.

    Enrolls the member, records a ``new_member`` / ``new_dependent`` life event,
    recomputes the policy premium, and issues an adjustment invoice for the
    prorated delta over the remaining period. Returns a summary dict with the
    new member, the proration, and the issued invoice.
    """
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    if policy.status != "active":
        raise ValueError(
            f"Policy {policy_id} is not active (is '{policy.status}'); census "
            "changes require an active policy"
        )

    event_type = "new_dependent" if (relationship or "").lower().startswith(
        ("spouse", "child", "dependent")
    ) else "new_member"

    member, added_premium = _add_effect(
        db,
        policy_id=policy_id,
        member_number=member_number,
        first_name=first_name,
        last_name=last_name,
        effective_date=effective_date,
        relationship=relationship,
        benefit_id=benefit_id,
        election_amount=election_amount,
        actor_id=actor_id,
    )

    record_event(
        db,
        policy_id=policy_id,
        member_id=member.id,
        event_type=event_type,
        effective_date=effective_date,
        actor_id=actor_id,
        details=f"member_number={member_number}",
    )

    proration = prorate_policy(
        db,
        policy_id=policy_id,
        effective_date=effective_date,
        added_premium=added_premium,
    )
    reason = f"{event_type} effective {effective_date.isoformat()}"
    invoice = None
    if proration["adjustment"] != 0.0:
        from app.services.invoices import issue_adjustment_invoice

        invoice = issue_adjustment_invoice(
            db,
            policy_id=policy_id,
            adjustment=proration["adjustment"],
            effective_date=effective_date,
            reason=reason,
        )
    _notify(db, policy_id, event_type, effective_date, proration["adjustment"], actor_id)

    return {
        "member_id": member.id,
        "member_number": member.member_number,
        "event_type": event_type,
        "effective_date": effective_date.isoformat(),
        "added_premium": added_premium,
        "proration": proration,
        "invoice_id": invoice.id if invoice else None,
        "invoice_number": invoice.invoice_number if invoice else None,
        "adjustment": proration["adjustment"],
        "new_premium": proration["new_premium"],
    }


def census_remove(
    db,
    *,
    member_id: int,
    effective_date: dt.date,
    actor_id: int | None = None,
) -> dict:
    """Remove a member (or dependent) mid-policy-cycle.

    Terminates the member, records a ``member_departed`` /
    ``dependent_departed`` life event, recomputes the policy premium, and issues
    an adjustment invoice for the prorated credit over the remaining period.
    Returns a summary dict with the member, the proration, and the invoice.
    """
    member = db.get(Member, member_id)
    if member is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    policy_id = member.policy_id
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    event_type = (
        "dependent_departed"
        if (member.relationship or "").lower().startswith(("spouse", "child", "dependent"))
        else "member_departed"
    )

    departed_premium = float(per_member_premium(db, member_id=member_id) or 0)

    terminate_member(db, member_id=member_id, termination_date=effective_date)
    record_event(
        db,
        policy_id=policy_id,
        member_id=member.id,
        event_type=event_type,
        effective_date=effective_date,
        actor_id=actor_id,
        details=f"member_number={member.member_number}",
    )

    proration = prorate_policy(
        db,
        policy_id=policy_id,
        effective_date=effective_date,
        departed_premium=departed_premium,
    )
    reason = f"{event_type} effective {effective_date.isoformat()}"
    invoice = None
    if proration["adjustment"] != 0.0:
        from app.services.invoices import issue_adjustment_invoice

        invoice = issue_adjustment_invoice(
            db,
            policy_id=policy_id,
            adjustment=proration["adjustment"],
            effective_date=effective_date,
            reason=reason,
        )
    _notify(db, policy_id, event_type, effective_date, proration["adjustment"], actor_id)

    return {
        "member_id": member.id,
        "member_number": member.member_number,
        "event_type": event_type,
        "effective_date": effective_date.isoformat(),
        "departed_premium": departed_premium,
        "proration": proration,
        "invoice_id": invoice.id if invoice else None,
        "invoice_number": invoice.invoice_number if invoice else None,
        "adjustment": proration["adjustment"],
        "new_premium": proration["new_premium"],
    }


def _notify(
    db,
    policy_id: int,
    event_type: str,
    effective_date: dt.date,
    adjustment: float,
    actor_id: int | None,
) -> None:
    """Best-effort email notification. Never raises — a broken send must not
    fail a census change."""
    try:
        emails.notify_census_change(
            db,
            policy_id=policy_id,
            event_type=event_type,
            effective_date=effective_date,
            adjustment=adjustment,
            actor_id=actor_id,
        )
    except Exception:
        # SMTP is typically off in development; a send failure is informational.
        pass


def list_life_events(policy_id: int | None = None) -> list:
    """Thin list view over life events for the member-list partial."""
    db = SessionLocal()
    try:
        from app.services.life_events import list_events

        return list_events(db, policy_id=policy_id)
    finally:
        db.close()
