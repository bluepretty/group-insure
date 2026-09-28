"""Policy CRUD + helpers. A policy belongs to a product and a policyholder Party.

Policy numbers must be unique per product, enforced by a DB composite unique
index (uq_policy_policy_number) added in the model.
"""
import datetime as dt

from sqlalchemy import select

from app.enums import PolicyStatus, validate_transition
from app.models.policy import Policy
from app.models.product import Product
from app.services.audit import record_log
from app.services.lookup import validate_kind_code

# A policy must be lapsed this long before it can be closed.
GRACE_DAYS = 30

# Policy lifecycle values and legal transitions, sourced from app.enums so the
# value set has one definition the routes, models, and tests all check against.



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
    if to_status not in PolicyStatus.ALL:
        raise ValueError(f"Invalid status: {to_status!r}")
    # The value set is also table-backed (see services.lookup): an unknown status
    # cannot be written even if it somehow matches the enum set, and a
    # deactivated status cannot be transitioned into.
    validate_kind_code(db, "policy_statuses", to_status)
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    validate_transition(
        policy.status, to_status, PolicyStatus.TRANSITIONS
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


def renew(
    db,
    *,
    policy_id: int,
    new_start: dt.date,
    new_end: dt.date,
    premium: float | None = None,
    due_offset_days: int = 30,
) -> dict:
    """Renew a settled, active policy into a new term.

    Renewal extends a policy past its ``end_date`` and bills the next term. It is
    only valid for an **active** policy that has been fully settled for its
    current term (no outstanding invoice): that keeps the one-outstanding-
    invoice-per-policy invariant that :func:`create_invoice` enforces.

    ``new_start`` must be the day after the current ``end_date`` (continuity of
    coverage); ``new_end`` must be strictly later and must not overlap the
    current term. The period is rewritten to ``new_start -> new_end``. When
    ``premium`` is given it is applied, otherwise the premium is refreshed from
    the current roster (the same path ``create_invoice`` uses). Issues the
    next-term invoice with a due date of ``new_end + due_offset_days`` and logs
    ``policy_renewed``. Returns a summary dict.
    """
    from app.services.invoices import _outstanding_invoice, create_invoice

    if new_end <= new_start:
        raise ValueError(
            f"Renewal end_date ({new_end.isoformat()}) must be later than its "
            f"start_date ({new_start.isoformat()})"
        )

    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    if policy.status != "active":
        raise ValueError(f"Only an active policy can be renewed (is '{policy.status}')")
    if policy.start_date is None or policy.end_date is None:
        raise ValueError(
            "Policy must have coverage dates (start_date and end_date) to renew"
        )

    expected_start = policy.end_date + dt.timedelta(days=1)
    if new_start != expected_start:
        raise ValueError(
            f"Renewal must start the day after the current term ends "
            f"(expected {expected_start.isoformat()}, got {new_start.isoformat()})"
        )
    if new_start <= policy.start_date:
        raise ValueError(
            f"Renewal must not overlap the current term "
            f"(current term starts {policy.start_date.isoformat()})"
        )

    # Apply the new premium (or refresh from the current roster), then bill the
    # new term and extend the period — all in one transaction. A mid-step
    # failure (for example a concurrent renewal that left an outstanding
    # invoice) rolls back the premium change too, so the policy is left exactly
    # as it was rather than a changed premium with no invoice.
    try:
        if premium is not None:
            policy.premium = round(float(premium), 2)
        else:
            from app.services.premiums import refresh_policy_premium

            refresh_policy_premium(db, policy_id=policy_id)
        policy = db.get(Policy, policy_id)

        # Bill the new term. create_invoice refreshes the premium again (idempotent)
        # and snapshots total_amount; it also refuses if an outstanding invoice was
        # somehow created concurrently, preserving the one-outstanding-invoice rule.
        outstanding = _outstanding_invoice(db, policy_id=policy_id)
        if outstanding is not None:
            raise ValueError(
                f"A policy can only be renewed when its current term is fully settled; "
                f"{outstanding.status} invoice {outstanding.invoice_number} is still "
                f"outstanding"
            )

        invoice = create_invoice(
            db,
            policy_id=policy_id,
            issued_date=new_start,
            due_date=(new_end + dt.timedelta(days=due_offset_days)),
            premium=premium,
        )
        policy = db.get(Policy, policy_id)

        # Extend the period into the new term on the policy row.
        policy.start_date = new_start
        policy.end_date = new_end
        db.commit()
    except Exception:
        db.rollback()
        raise

    record_log(
        db,
        action="policy_renewed",
        entity="Policy",
        entity_id=policy_id,
        details=(
            f"term={policy.start_date.isoformat()}..{policy.end_date.isoformat()} "
            f"new_premium={policy.premium} invoice={invoice.invoice_number}"
        ),
    )
    return {
        "policy_id": policy_id,
        "new_start": policy.start_date.isoformat(),
        "new_end": policy.end_date.isoformat(),
        "premium": float(policy.premium or 0.0),
        "invoice_number": invoice.invoice_number,
        "invoice_total": float(invoice.total_amount),
    }
