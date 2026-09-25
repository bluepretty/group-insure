"""Claims API — view and adjudicate claims against a policy's benefits.

Lifecycle: open -> under_review -> paid|denied -> closed (closed is terminal).
Only underwriters may change a claim's status (manage_claims); any logged-in
account may view claims on policies they can see (view_claims).

Each list/detail pair has two forms: a JSON endpoint (``GET /api/claims`` and
``GET /api/claims/{claim_id}``) and an HTMX partial (``GET /api/claims/list``
and ``GET /api/claims/detail``) that renders into the server-rendered dashboard.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, get_db, require_role
from app.api.auth import User
from app.models import Claim, User
from app.services import claims as claim_service
from app.view import templates

router = APIRouter(prefix="/api/claims", tags=["claims"])


# --- Pydantic response models -------------------------------------------------


class ClaimSummaryModel(BaseModel):
    id: int
    policy_id: int
    member_id: int | None
    benefit_id: int | None
    status: str
    claim_amount: float | None
    paid_amount: float
    created_at: datetime


class ClaimModel(BaseModel):
    id: int
    policy_id: int
    member_id: int | None
    benefit_id: int | None
    status: str
    claim_amount: float | None
    paid_amount: float
    reason: str | None
    created_at: datetime
    updated_at: datetime


class _CreateRequest(BaseModel):
    policy_id: int
    member_id: int | None = None
    benefit_id: int | None = None
    claim_amount: float | None = None
    reason: str | None = None


class _AdjudicateRequest(BaseModel):
    paid_amount: float


# --- List ---------------------------------------------------------------------


@router.get("", response_model=list[ClaimSummaryModel])
def list_claims_json(
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_claims")),
    policy_id: int | None = None,
    member_id: int | None = None,
) -> list[ClaimSummaryModel]:
    """JSON list of claims, optionally scoped to one policy or member."""
    return claim_service.list_claims(db, policy_id=policy_id, member_id=member_id)


@router.get("/list")
def list_claims_partial(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_claims")),
    policy_id: int | None = None,
    member_id: int | None = None,
) -> HTMLResponse:
    """HTMX partial: the claims list, swapped into the dashboard."""
    claims = claim_service.list_claims(db, policy_id=policy_id, member_id=member_id)
    return templates.TemplateResponse(
        request,
        "partials/claim_list.html",
        {"claims": claims},
    )


# --- Create -------------------------------------------------------------------


@router.post("", response_model=ClaimModel)
def create_claim(
    body: _CreateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_claims")),
) -> ClaimModel:
    """File a new claim against a policy's benefit."""
    try:
        return claim_service.create_claim(
            db,
            policy_id=body.policy_id,
            member_id=body.member_id,
            benefit_id=body.benefit_id,
            claim_amount=body.claim_amount,
            reason=body.reason,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- Detail -------------------------------------------------------------------


@router.get("/{claim_id}", response_model=ClaimModel)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_claims")),
) -> ClaimModel:
    """JSON detail for a single claim."""
    try:
        return claim_service.get_claim(db, claim_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


@router.get("/detail")
def claim_detail_partial(
    request: Request,
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("view_claims")),
) -> HTMLResponse:
    """HTMX partial: a single claim's detail with action buttons."""
    try:
        claim = claim_service.get_claim(db, claim_id)
    except ValueError:
        return HTMLResponse("<p class='text-muted'>Claim not found.</p>")
    return templates.TemplateResponse(
        request,
        "partials/claim_detail.html",
        {
            "claim": claim,
            "can_manage": _has_permission(user, "manage_claims"),
        },
    )


# --- Lifecycle ----------------------------------------------------------------


@router.post("/{claim_id}/review", response_model=ClaimModel)
def mark_under_review(
    claim_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_claims")),
) -> ClaimModel:
    """Move an open claim to under_review."""
    try:
        return claim_service.mark_under_review(db, claim_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post("/{claim_id}/adjudicate", response_model=ClaimModel)
def adjudicate(
    claim_id: int,
    body: _AdjudicateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_claims")),
) -> ClaimModel:
    """Set the paid amount; the claim becomes paid or denied accordingly."""
    try:
        return claim_service.adjudicate(db, claim_id=claim_id, paid_amount=body.paid_amount)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post("/{claim_id}/close", response_model=ClaimModel)
def close_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_claims")),
) -> ClaimModel:
    """Close a paid or denied claim (terminal)."""
    try:
        return claim_service.close_claim(db, claim_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
