"""Life-event listing endpoint (Stage 12).

The life-event log is the durable "why/when" trail for mid-term census changes
(additions/removals). This thin read route renders the newest events for a
policy as an HTMX partial, so the member-list page can surface the audit trail
that the proration path records.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.services.life_events import list_events
from app.view import templates

router = APIRouter(prefix="/api/members", tags=["members"])


@router.get("/life-events")
def life_events(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_members")),
) -> HTMLResponse:
    events = list_events(db, policy_id=policy_id)
    return templates.TemplateResponse(
        request,
        "partials/life_events.html",
        {"events": events},
    )
