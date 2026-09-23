"""Audit-log listing endpoint and HTMX partial."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.models.audit import AuditLog
from app.view import templates

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/recent")
def audit_recent(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_dashboard")),
) -> HTMLResponse:
    entries = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50)
    ).all()
    return templates.TemplateResponse(
        request,
        "partials/audit_recent.html",
        {"entries": entries},
    )
