"""Reports endpoints (Stage 8): a cross-domain platform snapshot.

``build_report`` aggregates across policies, members, benefits, claims and
invoices; the JSON endpoint returns the flat dict, and the HTMX-partial renders
the report cards into the dashboard ``#content``. Both are gated on
``view_dashboard`` — a cross-domain roll-up that every section already shares,
so no dedicated ``view_reports`` permission is introduced.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.view import templates

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def report_json(
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_dashboard")),
) -> dict:
    """JSON snapshot of the whole platform (see services/reports.py)."""
    from app.services.reports import build_report

    return build_report(db)


@router.get("/list")
def report_partial(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_dashboard")),
) -> HTMLResponse:
    """HTMX-partial: the report cards, swapped into the dashboard."""
    from app.services.reports import build_report

    report = build_report(db)
    return templates.TemplateResponse(
        request,
        "partials/report_list.html",
        {"report": report},
    )
