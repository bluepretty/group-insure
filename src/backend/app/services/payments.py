"""Payment recording + reconciliation (Stage 6 billing).

Payments are money received against an invoice. Recording or voiding a payment
reconciles the invoice's ``paid_amount`` and ``status`` atomically with the
payment change.
"""
import datetime as dt

from sqlalchemy import select

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.policy import Policy
from app.services.audit import record_log
from app.services.invoices import _reconcile_invoice
from app.services.policies import change_policy_status


def list_payments(db) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.created_at.desc())
    return db.scalars(stmt).all()


def get_payment(db, payment_id: int) -> Payment | None:
    return db.get(Payment, payment_id)


def _total_posted(db, invoice_id: int) -> float:
    payments = db.scalars(
        select(Payment)
        .where(Payment.invoice_id == invoice_id, Payment.status == "posted")
    ).all()
    return sum(p.amount or 0 for p in payments)


def _reconcile(db, invoice: Invoice) -> Invoice:
    """Re-run status from all posted payments (idempotent)."""
    return _reconcile_invoice(db, invoice)


def record_payment(
    db,
    *,
    invoice_id: int,
    amount: float,
    method: str | None = None,
    reference: str | None = None,
    payment_date: dt.datetime | None = None,
) -> Payment:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise ValueError(f"Unknown invoice_id: {invoice_id}")
    if amount is None or amount <= 0:
        raise ValueError("Payment amount must be a positive number")

    payment = Payment(
        invoice_id=invoice_id,
        amount=amount,
        method=method,
        reference=reference,
        status="posted",
        payment_date=payment_date or dt.datetime.now(dt.timezone.utc),
    )
    # Persist the payment and reconcile the invoice in a single transaction.
    # The payment must be flushed before reconciling — ``_reconcile`` queries
    # the DB for posted payments, so a not-yet-flushed payment would not be
    # counted. One commit (the original code committed twice) means a crash
    # cannot leave the payment durable while the invoice's status stays stale.
    db.add(payment)
    db.flush()
    _reconcile(db, invoice)
    db.commit()
    if invoice.status == "paid" and invoice.policy_id is not None:
        # Reinstating a lapsed policy is the natural effect of full payment.
        # Only the lapsed → active transition is a real change; an active
        # policy that simply pays its invoice stays active.
        policy = db.get(Policy, invoice.policy_id)
        if policy is not None and policy.status == "lapsed":
            change_policy_status(db, policy_id=invoice.policy_id, to_status="active")
    record_log(
        db,
        action="payment_recorded",
        entity="Payment",
        entity_id=payment.id,
        details=(
            f"invoice_id={invoice_id} amount={amount} "
            f"invoice_status={invoice.status}"
        ),
    )
    return payment


def void_payment(db, *, payment_id: int) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise ValueError(f"Unknown payment_id: {payment_id}")
    if payment.status != "posted":
        raise ValueError("Only posted payments can be voided")
    payment.status = "void"
    invoice = payment.invoice_id is not None and db.get(Invoice, payment.invoice_id)
    if invoice is not None:
        _reconcile(db, invoice)
    db.commit()
    record_log(
        db,
        action="payment_void",
        entity="Payment",
        entity_id=payment.id,
        details=f"invoice_id={payment.invoice_id}",
    )
    return payment
