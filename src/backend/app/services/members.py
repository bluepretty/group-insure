"""Member CRUD + helpers. A member is an individual enrolled under a policy.

Member numbers must be unique per policy, enforced by a DB composite unique
index (uq_member_policy_number) added in the model.
"""
import datetime as dt

from sqlalchemy import func, select

from app.models.member import Member
from app.models.member_benefit import MemberBenefit
from app.models.policy import Policy
from app.models.claim import Claim
from app.services.audit import record_log
from app.services.lookup import validate_kind_code


VALID_STATUS = ("active", "inactive", "terminated")


def list_members(
    db,
    *,
    party_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Member]:
    stmt = select(Member)
    if party_id is not None:
        stmt = stmt.where(Member.party_id == party_id)
    stmt = stmt.order_by(Member.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    return db.scalars(stmt).all()


def get_member(db, member_id: int) -> Member | None:
    return db.get(Member, member_id)


def enroll_member(
    db,
    *,
    policy_id: int,
    party_id: int | None = None,
    organization_id: int | None = None,
    member_number: str,
    first_name: str,
    last_name: str,
    date_of_birth: dt.date | None = None,
    gender: str | None = None,
    relationship_code: str | None = None,
    position_code: str | None = None,
    annual_salary: float | None = None,
    effective_date: dt.date | None = None,
) -> Member:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    existing = db.scalar(
        select(Member).where(
            Member.policy_id == policy_id,
            Member.member_number == member_number,
        )
    )
    if existing is not None:
        raise ValueError(f"Member number '{member_number}' already exists for this policy")
    # The relationship and position are into lookup tables: refuse a code that
    # isn't a live value so a member can never point at an unknown row.
    if relationship_code is not None:
        validate_kind_code(db, "relationships", relationship_code)
    if position_code is not None:
        validate_kind_code(db, "positions", position_code)
    member = Member(
        policy_id=policy_id,
        party_id=party_id,
        organization_id=organization_id,
        member_number=member_number,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        gender=gender,
        relationship_code=relationship_code,
        position_code=position_code,
        annual_salary=annual_salary,
        effective_date=effective_date,
    )
    db.add(member)
    db.commit()
    record_log(
        db,
        action="member_enroll",
        entity="Member",
        entity_id=member.id,
        details=f"policy_id={policy_id}",
    )
    return member


def update_member(
    db,
    *,
    member: Member,
    first_name: str | None = None,
    last_name: str | None = None,
    relationship_code: str | None = None,
    position_code: str | None = None,
    annual_salary: float | None = None,
) -> Member:
    """Update a member's mutable profile fields.

    Nothing is committed here so the caller can bundle the write with an audit
    log in one transaction.
    """
    if first_name is not None:
        member.first_name = first_name
    if last_name is not None:
        member.last_name = last_name
    if relationship_code is not None:
        validate_kind_code(db, "relationships", relationship_code)
        member.relationship_code = relationship_code
    if position_code is not None:
        validate_kind_code(db, "positions", position_code)
        member.position_code = position_code
    if annual_salary is not None:
        member.annual_salary = annual_salary
    return member


def member_usage(db, member_id: int) -> dict:
    """Counts of rows that would be orphaned if ``member_id`` were soft-deleted.

    A member's row is referenced by its own claims and by the single
    MemberBenefit election it holds. ``{"ok": True}`` means it is safe to mark
    the member inactive.
    """
    claims = db.scalar(
        select(func.count()).select_from(Claim).where(Claim.member_id == member_id)
    )
    elections = db.scalar(
        select(func.count())
        .select_from(MemberBenefit)
        .where(MemberBenefit.member_id == member_id)
    )
    return {
        "ok": claims == 0 and elections == 0,
        "claims": claims,
        "elections": elections,
    }


def terminate_member(
    db,
    *,
    member_id: int,
    termination_date: dt.date | None = None,
) -> Member:
    member = db.get(Member, member_id)
    if member is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    member.status = "terminated"
    member.termination_date = termination_date or dt.date.today()
    db.commit()
    record_log(
        db,
        action="member_terminate",
        entity="Member",
        entity_id=member.id,
        details=f"termination_date={member.termination_date}",
    )
    return member
