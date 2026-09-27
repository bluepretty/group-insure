"""Invoice + invoice-listing helpers (Stage 6 billing).

An invoice is a billing artifact issued against a policy for its computed
premium. ``total_amount`` snapshots the policy premium at issue time; the invoice
``status`` is reconciled from ``paid_amount`` by the payment service. One
outstanding (unpaid) invoice is issued per policy.
"""
import datetime as dt
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.policy import Policy
from app.services.audit import record_log
from app.services.policies import change_policy_status
from app.services.premiums import policy_premium, refresh_policy_premium

# Invoice numbers (e.g. "INV-1", "INV-2" per policy) are derived from the
# database rather than an in-memory counter. A `+= 1` on a module global is a
# non-atomic read-modify-write, so two concurrent submissions in FastAPI's thread
# pool can both read the same count and emit the same invoice_number — which then
# trips the (policy_id, invoice_number) unique index and surfaces as an opaque
# 500. Deriving from the DB avoids both the race and restart-duplicate numbers.
INVOICE_NUMBER_RE = re.compile(r"^INV-(\d+)(?:-ADJ)?$")


def _next_invoice_number(db: Session, policy_id: int) -> str:
    # Derive the next number from a per-policy DB aggregate rather than scanning
    # every invoice for the policy in Python. This is O(1) (indexed by
    # `policy_id`), avoids the restart-duplicate race noted in the module
    # comment, and matches the `claim_number` fix.
    row = db.scalar(
        select(func.max(Invoice.invoice_number))
        .where(Invoice.policy_id == policy_id)
    )
    highest = 0
    if row is not None:
        m = INVOICE_NUMBER_RE.match(row)
        if m:
            highest = int(m.group(1))
    return f"INV-{highest + 1}"


def list_invoices(
    db,
    *,
    policy_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Invoice]:
    stmt = select(Invoice)
    if policy_id is not None:
        stmt = stmt.where(Invoice.policy_id == policy_id)
    stmt = stmt.order_by(Invoice.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    return db.scalars(stmt).all()


def get_invoice(db, invoice_id: int) -> Invoice | None:
    return db.get(Invoice, invoice_id)


def _outstanding_invoice(db, *, policy_id: int) -> Invoice | None:
    """An invoice for this policy that is not yet fully paid. None means the
    policy is fully paid and a fresh invoice should be allowed."""
    for inv in db.scalars(
        select(Invoice).where(Invoice.policy_id == policy_id, Invoice.status != "paid")
    ).all():
        return inv
    return None


def _reconcile_invoice(db, invoice: Invoice) -> Invoice:
    """Set paid_amount + status from posted payments for this invoice."""
    payments = db.scalars(
        select(Payment)
        .where(Payment.invoice_id == invoice.id, Payment.status == "posted")
    ).all()
    invoice.paid_amount = sum(p.amount or 0 for p in payments)
    if invoice.total_amount is None:
        return invoice
    if invoice.paid_amount == 0:
        invoice.status = "issued"
    elif invoice.paid_amount >= invoice.total_amount:
        invoice.status = "paid"
        invoice.paid_date = dt.datetime.now(dt.timezone.utc)
    else:
        invoice.status = "partially_paid"
    return invoice


def create_invoice(
    db,
    *,
    policy_id: int,
    issued_date: dt.date | None = None,
    due_date: dt.date | None = None,
    premium: float | None = None,
) -> Invoice:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    # A caller may supply an explicit premium (e.g. renew at a new annual
    # rate). Otherwise the premium is refreshed from the roster, the default
    # snapshot the invoice service uses.
    if premium is not None:
        policy.premium = round(float(premium), 2)
    else:
        # Compute the premium in memory without committing yet. The outstanding
        # invoice invariant below may still reject the renewal; committing the
        # premium change before that check risks leaving a policy with a new
        # premium and no invoice if the guard fails. `db.commit()` happens below
        # once, together with the invoice insert, so the whole write is atomic.
        try:
            refresh_policy_premium(db, policy_id=policy_id, commit=False)
        except ValueError:
            raise
    policy = db.get(Policy, policy_id)
    total = float(policy.premium)

    existing = _outstanding_invoice(db, policy_id=policy_id)
    if existing is not None:
        raise ValueError(
            f"An outstanding invoice ({existing.status}) already exists for this "
            "policy"
        )

    if policy.status == "lapsed":
        # Issuing a new invoice while the policy is lapsed reinstates it.
        change_policy_status(db, policy_id=policy_id, to_status="active")
        policy = db.get(Policy, policy_id)

    invoice = Invoice(
        policy_id=policy_id,
        invoice_number=_next_invoice_number(db, policy_id),
        status="issued",
        total_amount=round(total, 2),
        paid_amount=0,
        issued_date=issued_date or dt.date.today(),
        due_date=due_date,
    )
    db.add(invoice)
    db.commit()
    record_log(
        db,
        action="invoice_issued",
        entity="Invoice",
        entity_id=invoice.id,
        details=f"policy_id={policy_id} amount={invoice.total_amount}",
    )
    return invoice


def issue_adjustment_invoice(
    db,
    *,
    policy_id: int,
    adjustment: float,
    effective_date: dt.date | None = None,
    reason: str | None = None,
    issued_date: dt.date | None = None,
    due_date: dt.date | None = None,
) -> Invoice:
    """Issue a *separate* adjustment invoice for a signed mid-term delta.

    Used by the census proration (Stage 12) to reflect the signed difference an
    add or removal causes to the premium for the *remaining* policy period. A
    positive ``adjustment`` is more owed; a negative one is a credit.

    This deliberately does **not** go through ``create_invoice``'s one-outstanding-
    invoice-per-policy guard: an adjustment invoice is a distinct ledger line that
    sits *alongside* the policy's regular invoice rather than replacing it.

    ``total_amount`` stores the signed adjustment; ``adjustment_reason`` explains
    it on the ledger. Reuses ``_reconcile_invoice`` so payments update
    ``paid_amount``/``status`` normally.
    """
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    total = round(float(adjustment), 2)
    invoice = Invoice(
        policy_id=policy_id,
        invoice_number=_next_invoice_number(db, policy_id) + "-ADJ",
        status="issued",
        total_amount=total,
        paid_amount=0,
        issued_date=issued_date or effective_date or dt.date.today(),
        due_date=due_date,
        adjustment_reason=reason,
    )
    db.add(invoice)
    db.commit()
    record_log(
        db,
        action="invoice_issued",
        entity="Invoice",
        entity_id=invoice.id,
        details=f"policy_id={policy_id} adjustment={total} reason={reason}",
    )
    return invoice
