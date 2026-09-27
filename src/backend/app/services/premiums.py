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
        # A member with no benefit election contributes zero premium; callers
        # (census removal, proration) expect 0, not a ValueError.
        return Decimal(0)
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
    # Batch the benefit lookups: the per-member helper issued one
    # ``MemberBenefit`` + one ``Benefit`` query *per* member (an N+1), and this
    # service is called on every renew, invoice issue, and census proration.
    # Load the elections and every benefit they reference in two queries, then
    # apply the identical per-member math so the totals are unchanged.
    elections = list(db.scalars(stmt))
    benefit_by_id = {}
    if elections:
        benefit_by_id = {
            b.id: b
            for b in db.scalars(
                select(Benefit).where(
                    Benefit.id.in_([e.benefit_id for e in elections])
                )
            )
        }
    breakdown = []
    total = Decimal(0)
    for election in elections:
        benefit = benefit_by_id.get(election.benefit_id)
        if benefit is None:
            # Mirrors per_member_premium: an unknown/missing benefit is an error.
            raise ValueError(f"Unknown benefit_id: {election.benefit_id}")
        rate = benefit.premium_rate
        amount = election.election_amount
        premium = (
            Decimal(str(rate)) * Decimal(str(amount))
            if rate is not None and amount is not None
            else Decimal(0)
        )
        election.premium = premium
        total += premium
        breakdown.append(
            {
                "member_id": election.member_id,
                "benefit_code": benefit.code,
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


def refresh_policy_premium(
    db,
    policy_id: int,
    *,
    commit: bool = True,
) -> Policy:
    """Compute (and optionally persist) a policy's premium, the source of truth
    the invoice service snapshots. Previously only computed in-memory, so when
    ``commit`` is True the value is written and the change recorded.

    Callers that are mid-transaction with an outstanding invariant to check
    pass ``commit=False``: the premium is computed in-memory so the caller can
    decide, in a single commit, whether the change is worth persisting.
    """
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    policy_premium(db, policy_id=policy_id)
    if commit:
        db.commit()
        record_log(
            db,
            action="policy_premium_refresh",
            entity="Policy",
            entity_id=policy.id,
            details=f"premium={policy.premium}",
        )
    return policy
