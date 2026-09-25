"""Invoice + invoice-listing helpers (Stage 6 billing).

An invoice is a billing artifact issued against a policy for its computed
premium. ``total_amount`` snapshots the policy premium at issue time; the invoice
``status`` is reconciled from ``paid_amount`` by the payment service. One
outstanding (unpaid) invoice is issued per policy.
"""
import datetime as dt

from sqlalchemy import select

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.policy import Policy
from app.services.audit import record_log
from app.services.premiums import policy_premium, refresh_policy_premium

# A minimal, monotonic-ish invoice number per policy (e.g. "INV-1", "INV-2").
_INV_COUNT = {}


def _next_invoice_number(policy_id: int) -> str:
    count = _INV_COUNT.get(policy_id, 0) + 1
    _INV_COUNT[policy_id] = count
    return f"INV-{count}"


def list_invoices(
    db, *, policy_id: int | None = None
) -> list[Invoice]:
    stmt = select(Invoice)
    if policy_id is not None:
        stmt = stmt.where(Invoice.policy_id == policy_id)
    stmt = stmt.order_by(Invoice.created_at.desc())
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
) -> Invoice:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")

    try:
        refresh_policy_premium(db, policy_id=policy_id)
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

    invoice = Invoice(
        policy_id=policy_id,
        invoice_number=_next_invoice_number(policy_id),
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
