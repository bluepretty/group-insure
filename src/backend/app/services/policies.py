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

# A policy must be lapsed this long before it can be closed.
GRACE_DAYS = 30

# Allowed status transitions. A policy can move forward from "draft" to
# "active"; a non-paying policy lapses and can be reinstated or closed; once
# "closed" a policy is terminal. "active" -> "draft" is not allowed.
_ALLOWED: dict[str, set[str]] = {
    "draft": {"active"},
    "active": {"lapsed"},
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
    policy.status_changed_at = dt.datetime.now(dt.timezone.utc)
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


def laps_if_overdue(db, *, policy_id: int, today: dt.date | None = None) -> Policy | None:
    """Lap an active policy with an unpaid invoice past its due date.

    No-op when the policy is not active or the invoice is not overdue, in which
    case None is returned. When the policy lapses, ``change_policy_status``
    validates the transition and writes the ``policy_status_change`` audit
    record, so this function only decides whether to call it.
    """
    from app.services.invoices import _outstanding_invoice

    if today is None:
        today = dt.date.today()
    policy = db.get(Policy, policy_id)
    if policy is None or policy.status != "active":
        return None
    invoice = _outstanding_invoice(db, policy_id=policy_id)
    if invoice is None or invoice.due_date is None or invoice.due_date > today:
        return None
    return change_policy_status(db, policy_id=policy_id, to_status="lapsed")


def _lapsed_for(db, policy: Policy, today: dt.date | None = None) -> int | None:
    """Days the policy has been lapsed, or None if it is not currently lapsed.

    Uses ``status_changed_at`` (set by ``change_policy_status`` on every
    transition) as the single source of truth for "when did this status begin".
    ``today`` is injectable for tests.
    """
    if policy.status != "lapsed" or policy.status_changed_at is None:
        return None
    today = today or dt.date.today()
    changed_date = policy.status_changed_at.date()
    return max(0, (today - changed_date).days)


def close_policy(db, *, policy_id: int, today: dt.date | None = None) -> Policy:
    """Close a lapsed policy that has outlived the grace period.

    Only the ``lapsed -> closed`` transition is here, gated by ``GRACE_DAYS``.
    Raises ValueError if the policy is unknown, not lapsed, or still inside the
    grace window; raises 400 elsewhere via the API. Logs ``policy_closed``.
    """
    if today is None:
        today = dt.date.today()
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    if policy.status != "lapsed":
        raise ValueError(f"Only a lapsed policy can be closed (is '{policy.status}')")
    lapsed_days = _lapsed_for(db, policy, today=today)
    if lapsed_days is None or lapsed_days < GRACE_DAYS:
        raise ValueError(
            f"Policy {policy_id} has only been lapsed {lapsed_days} day(s); "
            f"wait until it has been lapsed {GRACE_DAYS} days before closing"
        )
    change_policy_status(db, policy_id=policy_id, to_status="closed")
    record_log(
        db,
        action="policy_closed",
        entity="Policy",
        entity_id=policy_id,
        details=f"lapsed_days={lapsed_days}",
    )
    return db.get(Policy, policy_id)
