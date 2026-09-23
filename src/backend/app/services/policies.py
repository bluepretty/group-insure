"""Policy CRUD + helpers. A policy belongs to a product and a policyholder Party.

Policy numbers must be unique per product, so that is enforced in the service
layer (a DB-level unique index is added when we move to Postgres).
"""
import datetime as dt

from sqlalchemy import select

from app.models.policy import Policy
from app.models.product import Product
from app.services.audit import record_log

VALID_STATUSES = ("draft", "active", "lapsed", "closed")

# Allowed status transitions. A policy can always move forward from "draft" and
# be reinstated once from "lapsed".
_ALLOWED: dict[str, set[str]] = {
    "draft": {"active", "closed"},
    "active": {"lapsed", "closed"},
    "lapsed": {"active", "closed"},
    "closed": set(),
}



def list_policies(db, *, party_id: int | None = None) -> list[Policy]:
    stmt = select(Policy)
    if party_id is not None:
        stmt = stmt.where(Policy.party_id == party_id)
    stmt = stmt.order_by(Policy.created_at.desc())
    return db.scalars(stmt).all()


def get_policy(db, policy_id: int) -> Policy | None:
    return db.get(Policy, policy_id)


def add_policy(
    db,
    *,
    policy_number: str,
    product_id: int,
    party_id: int | None = None,
    organization_id: int | None = None,
    underwriter_id: int | None = None,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    premium: float | None = None,
) -> Policy:
    product = db.get(Product, product_id)
    if product is None:
        raise ValueError(f"Unknown product_id: {product_id}")
    existing = db.scalar(
        select(Policy).where(
            Policy.product_id == product_id,
            Policy.policy_number == policy_number,
        )
    )
    if existing is not None:
        raise ValueError(f"Policy number '{policy_number}' already exists for this product")
    policy = Policy(
        policy_number=policy_number,
        product_id=product_id,
        party_id=party_id,
        organization_id=organization_id,
        underwriter_id=underwriter_id,
        start_date=start_date,
        end_date=end_date,
        premium=premium,
    )
    db.add(policy)
    db.commit()
    record_log(
        db,
        action="policy_create",
        entity="Policy",
        entity_id=policy.id,
        details=f"product_id={product_id}",
    )
    return policy


def change_policy_status(db, policy_id: int, to_status: str) -> Policy:
    if to_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {to_status!r}")
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    allowed = _ALLOWED.get(policy.status, set())
    if to_status not in allowed:
        raise ValueError(
            f"Cannot move policy {policy.status!r} -> {to_status!r}"
        )
    policy.status = to_status
    db.commit()
    record_log(
        db,
        action="policy_status_change",
        entity="Policy",
        entity_id=policy.id,
        details=f"from={policy.status} to={to_status}",
    )
    return policy
