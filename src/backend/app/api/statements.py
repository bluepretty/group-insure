"""Policy statement endpoints (Stage 11): HTML preview, PDF download, email.

A statement is a policy's reconciliation document — policy summary, the
policyholder's contact, the invoice and payment line items, and the running
totals. Three faces of the same underlying data:

* ``GET /{id}/statement`` renders the statement as an HTML partial so it can
  load inline into the app (print/zoom via the browser, no third-party JS).
* ``GET /{id}/statement.pdf`` streams the ReportLab-rendered PDF straight to the
  browser with an inline disposition, so the browser's own print/zoom controls
  work on it.
* ``POST /{id}/statement/send`` emails the PDF to the policyholder's stored,
  validated email. It is confirm-gated (``manage_billing``) and refuses cleanly
  when SMTP is not configured or no address is on file.

All three gate on ``view_billing``; only the send path additionally requires
``manage_billing``.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.services.emails import send_statement
from app.services.statements import build_statement, render_statement_pdf
from app.view import templates

router = APIRouter(prefix="/api/policies", tags=["statements"])


def _statement(policy_id: int, db: Session) -> dict:
    """Build one policy's statement, mapping an unknown id to a 400.

    :func:`build_statement` raises ``ValueError`` for a missing policy; the
    endpoints surface that as a 400 (not a 500) so callers can distinguish
    "no such policy" from a genuine server error.
    """
    try:
        return build_statement(db, policy_id=policy_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{policy_id}/statement")
def statement_preview(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("view_billing")),
) -> HTMLResponse:
    """Render the statement as an HTML partial for the inline preview modal.

    The response is a fragment (not a full page) that loads into the existing
    ``hx-target="#content"`` modal — the same pattern the invoice partial uses.
    """
    stmt = _statement(policy_id, db)
    return templates.TemplateResponse(
        request,
        "partials/statement.html",
        {
            "statement": stmt,
            "policy_id": policy_id,
            "can_send": _has_permission(user, "manage_billing"),
        },
    )


@router.get("/{policy_id}/statement.pdf")
def statement_pdf(
    policy_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_billing")),
) -> HTMLResponse:
    """Stream the statement PDF with an inline disposition so the browser's
    print/zoom works on it directly."""
    stmt = _statement(policy_id, db)
    pdf = render_statement_pdf(stmt)
    return HTMLResponse(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="statement-{stmt["policy_number"]}.pdf"'
        },
    )


class SendStatementModel(BaseModel):
    confirm: bool = True


@router.post("/{policy_id}/statement/send")
def statement_send(
    policy_id: int,
    payload: SendStatementModel,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_billing")),
) -> JSONResponse:
    """Email the statement to the policyholder's stored, validated email.

    Confirm-gated: an empty body defaults ``confirm`` to ``true`` (the only
    thing a real POST carries), so the confirmation lives in the request itself.
    Raises ``ValueError``/``EmailError`` -> 400 when SMTP is not configured or
    there is no recipient on file; the send is recorded in the audit log.
    """
    if not payload.confirm:
        return JSONResponse(
            status_code=400,
            content={"detail": "Send requires confirmation; pass {\"confirm\": true}"},
        )
    try:
        result = send_statement(db, policy_id=policy_id, actor_id=user.id)
    except (ValueError, RuntimeError) as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    return JSONResponse(
        content={
            "sent": True,
            "to": result["to"],
            "subject": result["subject"],
            "attachment": result["attachment"],
        }
    )
