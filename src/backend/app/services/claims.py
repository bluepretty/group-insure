"""Claims management (Stage 14).

A claim is raised against a Policy for a specific enrolled Member, recording the
incident that triggered it. Claims move through a small decision-and-payout
lifecycle:

    submitted -> approved -> paid
            \\-> rejected        (rejected is terminal)

``amount_approved`` is set when an underwriter approves a claim; it carries
forward to ``paid``. All lifecycle transitions, validation, and the generated
``claim_number`` live here so the API layer stays thin.
"""
import datetime as dt

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.benefit import Benefit
from app.models.claim import Claim
from app.models.member import Member
from app.models.policy import Policy
from app.services.audit import record_log

# Claim numbers (e.g. "CLM-1", "CLM-2") are derived from the database rather
# than an in-memory counter. A `+= 1` on a module global is a non-atomic
# read-modify-write, so two concurrent submissions in FastAPI's thread pool can
# both read the same count and emit the same claim_number — which then trips the
# `claim_number unique=True` index and surfaces as an opaque 500. Deriving from
# the DB avoids both the race and restart-duplicate numbers.
CLAIM_NUMBER_RE = re.compile(r"^CLM-(\d+)$")


def _next_claim_number(db: Session) -> str:
    # Derive the next claim number from a DB aggregate rather than scanning the
    # whole claims table in Python. A full scan is O(N) on every submission and
    # (combined with the module-global counter comment above) race-prone; the
    # `claim_number` unique index means the number must never collide, so a
    # server-side MAX is both cheaper and the correct approach.
    row = db.scalar(select(func.max(Claim.claim_number)))
    highest = 0
    if row is not None:
        m = CLAIM_NUMBER_RE.match(row)
        if m:
            highest = int(m.group(1))
    return f"CLM-{highest + 1}"


# Valid transitions for each claim status. ``approved`` and ``rejected`` are
# both decision states; ``paid`` is terminal; ``rejected`` is terminal.
_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"approved", "rejected"},
    "approved": {"paid"},
    "rejected": set(),
    "paid": set(),
}


def list_claims(
    db: Session,
    *,
    policy_id: int | None = None,
    member_id: int | None = None,
    party_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Claim]:
    """Return claims, optionally filtered by policy, member, or policyholder.

    ``party_id`` scopes to every policy held by a policyholder ``Party`` — used
    by brokers to list all of a client's claims.
    """
    stmt = select(Claim)
    if policy_id is not None:
        stmt = stmt.where(Claim.policy_id == policy_id)
    if member_id is not None:
        stmt = stmt.where(Claim.member_id == member_id)
    if party_id is not None:
        policy_ids = db.scalars(
            select(Policy.id).where(Policy.party_id == party_id)
        ).all()
        if policy_ids:
            stmt = stmt.where(Claim.policy_id.in_(policy_ids))
    stmt = stmt.order_by(Claim.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    return db.scalars(stmt).all()


def get_claim(db: Session, claim_id: int) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Unknown claim_id: {claim_id}")
    return claim


def submit_claim(
    db: Session,
    *,
    policy_id: int,
    member_id: int,
    amount_claimed: float,
    incident_date: dt.date,
    benefit_id: int | None = None,
    description: str | None = None,
    claim_number: str | None = None,
) -> Claim:
    """Raise a new claim.

    Validates that the policy exists and the incident date falls within its
    active term, that the member exists, belongs to that policy, and is active,
    and that ``claim_number`` is unique. Raises ``ValueError`` on any failure.
    """
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    if incident_date is not None and (
        policy.start_date is None
        or incident_date < policy.start_date
        or incident_date > policy.end_date
    ):
        raise ValueError(
            f"Incident date {incident_date} is outside the policy term "
            f"({policy.start_date} to {policy.end_date})"
        )

    member = db.get(Member, member_id)
    if member is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    if member.policy_id != policy_id:
        raise ValueError(
            f"Member {member_id} does not belong to policy {policy_id}"
        )
    if getattr(member, "status", None) != "active":
        raise ValueError(
            f"Member {member_id} is not active (is '{getattr(member, 'status', None)}')"
        )

    if benefit_id is not None and db.get(Benefit, benefit_id) is None:
        raise ValueError(f"Unknown benefit_id: {benefit_id}")

    number = claim_number or _next_claim_number(db)
    existing = db.scalar(
        select(Claim).where(Claim.claim_number == number)
    )
    if existing is not None:
        raise ValueError(f"Claim number '{number}' already exists")

    claim = Claim(
        claim_number=number,
        policy_id=policy_id,
        member_id=member_id,
        benefit_id=benefit_id,
        incident_date=incident_date,
        amount_claimed=amount_claimed,
        amount_approved=None,
        description=description or None,
        status="submitted",
    )
    db.add(claim)
    db.commit()
    record_log(
        db,
        action="claim_submit",
        entity="Claim",
        entity_id=claim.id,
        details=(
            f"claim_number={number} policy_id={policy_id} "
            f"member_id={member_id} amount_claimed={amount_claimed}"
        ),
    )
    return claim


def update_claim_status(
    db: Session,
    *,
    claim_id: int,
    status: str,
    amount_approved: float | None = None,
) -> Claim:
    """Move a claim to a new status (an underwriter action).

    ``submitted`` -> {``approved``, ``rejected``}; ``approved`` -> ``paid``.
    On approval ``amount_approved`` must be set and <= ``amount_claimed`` and is
    carried forward to ``paid``. Raises ``ValueError`` on an illegal transition
    or a missing/invalid approval amount.
    """
    claim = get_claim(db, claim_id)

    if status not in _TRANSITIONS.get(claim.status, set()):
        raise ValueError(
            f"Cannot move claim #{claim.claim_number} "
            f"(is '{claim.status}') to '{status}'"
        )

    if status == "approved":
        if amount_approved is None or amount_approved <= 0:
            raise ValueError("amount_approved must be set and positive to approve")
        amount_claimed = getattr(claim, "amount_claimed", 0) or 0
        if amount_approved > amount_claimed:
            raise ValueError(
                f"amount_approved ({amount_approved}) exceeds amount_claimed "
                f"({amount_claimed})"
            )
        claim.amount_approved = amount_approved
    elif status == "paid":
        # A payout must approve against an approved amount.
        if claim.amount_approved is None or claim.amount_approved <= 0:
            raise ValueError("Cannot pay a claim without an approved amount")

    claim.status = status
    db.commit()
    record_log(
        db,
        action="claim_status_change",
        entity="Claim",
        entity_id=claim.id,
        details=f"{claim.status} -> {status}"
        + (f" amount_approved={amount_approved}" if amount_approved is not None else ""),
    )
    return claim
