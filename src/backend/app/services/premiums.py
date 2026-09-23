"""Premium pricing + allocation.

A benefit carries a catalog-level per-unit ``premium_rate``; a member's
``election_amount`` is the base they elected. A member's premium is
``election_amount × premium_rate``; a policy's premium is the sum of its
member premiums. The computed premium is stored on the election so it is not
lost when the catalog rate changes later.
"""
from decimal import Decimal

from sqlalchemy import select

from app.models.benefit import Benefit
from app.models.member import Member
from app.models.member_benefit import MemberBenefit
from app.models.policy import Policy
from app.services.audit import record_log


def per_member_premium(db, member_id: int) -> Decimal:
    election = db.scalar(
        select(MemberBenefit).where(MemberBenefit.member_id == member_id)
    )
    if election is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    benefit = db.get(Benefit, election.benefit_id)
    if benefit is None:
        raise ValueError(f"Unknown benefit_id: {election.benefit_id}")

    rate = benefit.premium_rate
    amount = election.election_amount
    if rate is None or amount is None:
        return Decimal(0)
    return (Decimal(str(rate)) * Decimal(str(amount)))


def policy_premium(db, policy_id: int) -> dict:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    stmt = select(MemberBenefit).where(
        MemberBenefit.member_id.in_(
            select(Member.id).where(Member.policy_id == policy_id)
        )
    )
    breakdown = []
    total = Decimal(0)
    for election in db.scalars(stmt):
        premium = per_member_premium(db, election.member_id)
        election.premium = premium
        total += premium
        breakdown.append(
            {
                "member_id": election.member_id,
                "benefit_code": election.benefit.code,
                "amount": float(premium),
            }
        )
    policy.premium = total
    return {"policy_id": policy_id, "total": float(total), "breakdown": breakdown}


def set_election_amount(db, *, member_id: int, amount: float) -> MemberBenefit:
    election = db.scalar(
        select(MemberBenefit).where(MemberBenefit.member_id == member_id)
    )
    if election is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    if amount is None or amount < 0:
        raise ValueError("election_amount must be a non-negative number")

    # The election's benefit must belong to the member's policy's product.
    member = db.get(Member, member_id)
    if member is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    if election.benefit.product_id != member.policy.product_id:
        raise ValueError(
            f"Benefit belongs to product #{election.benefit.product_id}, not the "
            f"member's policy product #{member.policy.product_id}"
        )

    election.election_amount = Decimal(str(amount))
    election.premium = per_member_premium(db, member_id)
    db.commit()
    record_log(
        db,
        action="premium_recompute",
        entity="MemberBenefit",
        entity_id=election.id,
        details=f"amount={amount} premium={election.premium}",
    )
    return election
