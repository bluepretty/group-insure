"""Claims + lifecycle (Stage 7).

A claim is a record raised against a policy for a covered benefit. Claims move
through a small state machine:

    open -> under_review -> paid | denied -> closed (closed is terminal)

Underwriters raise and adjudicate claims; brokers view them. All lifecycle
transitions are enforced here so the API layer stays thin.
"""
from sqlalchemy import select

from app.models.claim import Claim
from app.models.member import Member
from app.models.benefit import Benefit
from app.models.policy import Policy
from app.services.audit import record_log

# Valid transitions for each claim status. ``closed`` is terminal (no out-edges).
_TRANSITIONS: dict[str, set[str]] = {
    "open": {"under_review"},
    "under_review": {"paid", "denied"},
    "paid": {"closed"},
    "denied": {"closed"},
    "closed": set(),
}


def list_claims(
    db, *, policy_id: int | None = None, member_id: int | None = None
) -> list[Claim]:
    stmt = select(Claim)
    if policy_id is not None:
        stmt = stmt.where(Claim.policy_id == policy_id)
    if member_id is not None:
        stmt = stmt.where(Claim.member_id == member_id)
    stmt = stmt.order_by(Claim.created_at.desc())
    return db.scalars(stmt).all()


def get_claim(db, claim_id: int) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Unknown claim_id: {claim_id}")
    return claim


def _transition(db, claim: Claim, to_status: str) -> Claim:
    allowed = _TRANSITIONS.get(claim.status, set())
    if to_status not in allowed:
        raise ValueError(
            f"Cannot move claim #{claim.id} from '{claim.status}' to '{to_status}'"
        )
    claim.status = to_status
    db.commit()
    return claim


def create_claim(
    db,
    *,
    policy_id: int,
    member_id: int | None = None,
    benefit_id: int | None = None,
    claim_amount: float | None = None,
    reason: str | None = None,
) -> Claim:
    if db.get(Policy, policy_id) is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    if member_id is not None and db.get(Member, member_id) is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    if benefit_id is not None and db.get(Benefit, benefit_id) is None:
        raise ValueError(f"Unknown benefit_id: {benefit_id}")
    claim = Claim(
        policy_id=policy_id,
        member_id=member_id,
        benefit_id=benefit_id,
        claim_amount=claim_amount,
        reason=reason or None,
        status="open",
        paid_amount=0,
    )
    db.add(claim)
    db.commit()
    record_log(
        db,
        action="claim_create",
        entity="Claim",
        entity_id=claim.id,
        details=f"policy_id={policy_id} claim_amount={claim_amount}",
    )
    return claim


def mark_under_review(db, claim_id: int) -> Claim:
    claim = get_claim(db, claim_id)
    return _transition(db, claim, "under_review")


def adjudicate(db, *, claim_id: int, paid_amount: float) -> Claim:
    claim = get_claim(db, claim_id)
    if paid_amount is None or paid_amount < 0:
        raise ValueError("paid_amount must be a non-negative number")
    if claim.status != "under_review":
        raise ValueError(
            f"Claim #{claim.id} must be 'under_review' to adjudicate "
            f"(is '{claim.status}')"
        )
    claim.paid_amount = paid_amount
    claim.status = "paid" if paid_amount > 0 else "denied"
    db.commit()
    record_log(
        db,
        action="claim_adjudicate",
        entity="Claim",
        entity_id=claim.id,
        details=f"paid_amount={paid_amount} status={claim.status}",
    )
    return claim


def close_claim(db, claim_id: int) -> Claim:
    claim = get_claim(db, claim_id)
    if claim.status not in {"paid", "denied"}:
        raise ValueError(
            f"Claim #{claim.id} must be 'paid' or 'denied' to close "
            f"(is '{claim.status}')"
        )
    return _transition(db, claim, "closed")
