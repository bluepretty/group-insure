"""Billing endpoints (Stage 6): invoices + payments.

An invoice bills a policy for its computed premium; payments are money received
against an invoice. Underwriters issue invoices and record/void payments
(``manage_billing``); brokers view invoices (``view_billing``).
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.models.invoice import Invoice
from app.models.payment import Payment
from app.services.invoices import (
    create_invoice,
    get_invoice,
    list_invoices,
)
from app.services.payments import (
    void_payment,
    list_payments,
    record_payment,
)
from app.view import templates

router = APIRouter(prefix="/api/billing", tags=["billing"])


class InvoiceModel(BaseModel):
    id: int
    policy_id: int | None = None
    invoice_number: str
    status: str
    total_amount: float | None = None
    paid_amount: float
    issued_date: date | None = None
    due_date: date | None = None


class PaymentModel(BaseModel):
    id: int
    invoice_id: int | None = None
    amount: float
    method: str | None = None
    reference: str | None = None
    status: str


@router.get("/invoices", response_model=list[InvoiceModel])
def list_invoices_endpoint(
    db: Session = Depends(get_db),
    policy_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
    _: None = Depends(require_role("view_billing")),
) -> list[InvoiceModel]:
    return list_invoices(db, policy_id=policy_id, limit=limit, offset=offset)


@router.get("/invoices/json")
def invoice_list_json(
    db: Session = Depends(get_db),
    policy_id: int | None = None,
    _: None = Depends(require_role("view_billing")),
) -> JSONResponse:
    invoices = list_invoices(db, policy_id=policy_id)
    return JSONResponse(
        content=[
            {
                "id": invoice.id,
                "policy_id": invoice.policy_id,
                "invoice_number": invoice.invoice_number,
                "status": invoice.status,
                "total_amount": float(invoice.total_amount)
                if invoice.total_amount is not None
                else None,
                "paid_amount": float(invoice.paid_amount),
                "issued_date": invoice.issued_date.isoformat()
                if invoice.issued_date
                else None,
                "due_date": invoice.due_date.isoformat()
                if invoice.due_date
                else None,
            }
            for invoice in invoices
        ]
    )


@router.get("/invoices/create-form")
def invoice_create_form(
    request: Request,
    db: Session = Depends(get_db),
    policy_id: int | None = None,
    _: None = Depends(require_role("view_billing")),
) -> HTMLResponse:
    if policy_id is None:
        return JSONResponse(status_code=400, content={"detail": "policy_id required"})
    invoice_list = list_invoices(db, policy_id=policy_id)
    existing = next((i for i in invoice_list if i.status != "paid"), None)
    return templates.TemplateResponse(
        request,
        "partials/invoice_create_form.html",
        {"policy_id": policy_id, "existing": existing},
    )


@router.get("/invoices/{invoice_id}")
def invoice_detail(
    request: Request,
    invoice_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_billing")),
) -> HTMLResponse:
    invoice = get_invoice(db, invoice_id=invoice_id)
    if invoice is None:
        return HTMLResponse("<p class='text-muted'>Invoice not found.</p>")
    # Scope the query to this invoice's payments instead of loading every
    # payment in the app and filtering in Python. A broker with thousands of
    # invoices must never pay for an O(N) scan of the whole payments table here.
    payments = db.scalars(
        select(Payment).where(Payment.invoice_id == invoice_id)
    ).all()
    return templates.TemplateResponse(
        request,
        "partials/invoice_detail.html",
        {"invoice": invoice, "payments": list(payments), "can_manage": True},
    )


@router.get("/payments", response_model=list[PaymentModel])
def list_payments_endpoint(
    db: Session = Depends(get_db),
    limit: int | None = None,
    offset: int | None = None,
    _: None = Depends(require_role("view_billing")),
) -> list[PaymentModel]:
    return list_payments(db, limit=limit, offset=offset)


@router.post("/invoices")
def invoice_create(
    request: Request,
    policy_id: int = Form(...),
    issued_date: date | None = Form(None),
    due_date: date | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_billing")),
) -> JSONResponse:
    try:
        invoice = create_invoice(
            db,
            policy_id=policy_id,
            issued_date=issued_date,
            due_date=due_date,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "status": invoice.status,
            "total_amount": float(invoice.total_amount)
                if invoice.total_amount is not None else None,
            "policy_id": invoice.policy_id,
        }
    )


@router.post("/invoices/{invoice_id}/payments")
def payment_create(
    request: Request,
    invoice_id: int,
    amount: float = Form(...),
    method: str = Form(""),
    reference: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_billing")),
) -> JSONResponse:
    try:
        payment = record_payment(
            db,
            invoice_id=invoice_id,
            amount=amount,
            method=method or None,
            reference=reference or None,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={
            "id": payment.id,
            "invoice_id": payment.invoice_id,
            "amount": float(payment.amount),
            "status": payment.status,
        }
    )


@router.post("/payments/{payment_id}/void")
def payment_void(
    payment_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_billing")),
) -> JSONResponse:
    try:
        payment = void_payment(db, payment_id=payment_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={
            "id": payment.id,
            "invoice_id": payment.invoice_id,
            "status": payment.status,
        }
    )
