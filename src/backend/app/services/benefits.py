"""Benefit + member-coverage election helpers.

A product offers a set of benefits; a member elects exactly one benefit.
Benefit code uniqueness (per product) is enforced by a DB composite unique
index (uq_benefit_product_code); the one-election-per-member rule is enforced
in the service layer.
"""
import datetime as dt
from decimal import Decimal

from sqlalchemy import select

from app.models.benefit import Benefit
from app.models.member import Member
from app.models.member_benefit import MemberBenefit
from app.models.product import Product
from app.services.audit import record_log
from app.services.premiums import per_member_premium


def list_benefits(db, *, product_id: int | None = None) -> list[Benefit]:
    stmt = select(Benefit)
    if product_id is not None:
        stmt = stmt.where(Benefit.product_id == product_id)
    stmt = stmt.order_by(Benefit.created_at.desc())
    return db.scalars(stmt).all()


def get_benefit(db, benefit_id: int) -> Benefit | None:
    return db.get(Benefit, benefit_id)


def add_benefit(
    db,
    *,
    product_id: int,
    code: str,
    name: str,
    description: str | None = None,
    benefit_type: str | None = None,
    coverage_amount: float | None = None,
    premium_rate: float | None = None,
) -> Benefit:
    product = db.get(Product, product_id)
    if product is None:
        raise ValueError(f"Unknown product_id: {product_id}")
    existing = db.scalar(
        select(Benefit).where(
            Benefit.product_id == product_id,
            Benefit.code == code,
        )
    )
    if existing is not None:
        raise ValueError(f"Benefit code '{code}' already exists for this product")
    benefit = Benefit(
        product_id=product_id,
        code=code,
        name=name,
        description=description or None,
        benefit_type=benefit_type or None,
        coverage_amount=coverage_amount,
        premium_rate=premium_rate,
    )
    db.add(benefit)
    db.commit()
    record_log(
        db,
        action="benefit_add",
        entity="Benefit",
        entity_id=benefit.id,
        details=f"product_id={product_id} code={code}",
    )
    return benefit


def set_benefit_rate(
    db, *, benefit_id: int, premium_rate: float
) -> Benefit:
    benefit = db.get(Benefit, benefit_id)
    if benefit is None:
        raise ValueError(f"Unknown benefit_id: {benefit_id}")
    if premium_rate is None or premium_rate < 0:
        raise ValueError("premium_rate must be a non-negative number")
    benefit.premium_rate = Decimal(str(premium_rate))
    db.commit()
    record_log(
        db,
        action="benefit_rate_change",
        entity="Benefit",
        entity_id=benefit.id,
        details=f"premium_rate={benefit.premium_rate}",
    )
    return benefit


def list_member_benefits(db, *, member_id: int | None = None) -> list[MemberBenefit]:
    stmt = select(MemberBenefit)
    if member_id is not None:
        stmt = stmt.where(MemberBenefit.member_id == member_id)
    stmt = stmt.order_by(MemberBenefit.created_at.desc())
    return db.scalars(stmt).all()


def elect_benefit(
    db,
    *,
    member_id: int,
    benefit_id: int,
    election_amount: float | None = None,
) -> MemberBenefit:
    member = db.get(Member, member_id)
    if member is None:
        raise ValueError(f"Unknown member_id: {member_id}")
    benefit = db.get(Benefit, benefit_id)
    if benefit is None:
        raise ValueError(f"Unknown benefit_id: {benefit_id}")

    # A member may only elect a benefit that belongs to their policy's product.
    product_id = member.policy.product_id
    if benefit.product_id != product_id:
        raise ValueError(
            f"Benefit belongs to product #{benefit.product_id}, not the "
            f"policy's product #{product_id}"
        )

    existing = db.scalar(
        select(MemberBenefit).where(MemberBenefit.member_id == member_id)
    )
    if existing is not None:
        raise ValueError(
            "Member already elected a benefit"
            if existing.benefit_id != benefit_id
            else "Member already elected this benefit"
        )

    member_benefit = MemberBenefit(
        member_id=member_id,
        benefit_id=benefit_id,
        election_amount=election_amount,
    )
    db.add(member_benefit)
    db.commit()
    member_benefit.premium = per_member_premium(db, member_id=member_id)
    record_log(
        db,
        action="benefit_elect",
        entity="MemberBenefit",
        entity_id=member_benefit.id,
        details=f"member_id={member_id} benefit_id={benefit_id}",
    )
    return member_benefit
