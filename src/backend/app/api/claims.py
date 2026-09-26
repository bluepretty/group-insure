"""Claims API — submit and adjudicate claims against a policy's members.

A claim is raised against a Policy for a specific enrolled Member. Claims move
through a decision-and-payout lifecycle:

    submitted -> approved -> paid
            \\-> rejected        (rejected is terminal)

RBAC: any logged-in account with ``view_claims`` (broker + underwriter) may
submit a claim or view claims on policies they can see; only an underwriter with
``manage_claims`` may change a claim's status.

Each list/detail pair has two forms: a JSON endpoint (``GET /api/claims`` and
``GET /api/claims/{claim_id}``) and an HTMX partial (``GET /api/claims/list``
and ``GET /api/claims/detail``) that renders into the server-rendered dashboard.
"""
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role
from app.core.database import get_db
from app.models import User
from app.services import claims as claim_service
from app.services.policies import list_policies
from app.view import templates

router = APIRouter(prefix="/api/claims", tags=["claims"])


# --- Pydantic response models -------------------------------------------------


class ClaimSummaryModel(BaseModel):
    id: int
    claim_number: str
    policy_id: int
    member_id: int
    benefit_id: int | None
    status: str
    incident_date: dt.date
    amount_claimed: float
    amount_approved: float | None


class ClaimModel(BaseModel):
    id: int
    claim_number: str
    policy_id: int
    member_id: int
    benefit_id: int | None
    status: str
    incident_date: dt.date
    amount_claimed: float
    amount_approved: float | None
    description: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class _SubmitRequest(BaseModel):
    policy_id: int
    member_id: int
    amount_claimed: float
    incident_date: dt.date
    benefit_id: int | None = None
    description: str | None = None


class _StatusRequest(BaseModel):
    status: str
    amount_approved: float | None = None


# --- List ---------------------------------------------------------------------


@router.get("", response_model=list[ClaimSummaryModel])
def list_claims_json(
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_claims")),
    policy_id: int | None = None,
    member_id: int | None = None,
    party_id: int | None = None,
) -> list[ClaimSummaryModel]:
    """JSON list of claims, optionally scoped to a policy, member, or party."""
    return claim_service.list_claims(
        db, policy_id=policy_id, member_id=member_id, party_id=party_id
    )


@router.get("/list")
def list_claims_partial(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("view_claims")),
    policy_id: int | None = None,
    member_id: int | None = None,
    party_id: int | None = None,
) -> HTMLResponse:
    """HTMX partial: the claims list, swapped into the dashboard."""
    claims = claim_service.list_claims(
        db, policy_id=policy_id, member_id=member_id, party_id=party_id
    )
    return templates.TemplateResponse(
        request,
        "partials/claim_list.html",
        {
            "claims": claims,
            "can_manage": _has_permission(user, "manage_claims"),
            "policies": list_policies(db),
            "today": dt.date.today(),
        },
    )


# --- Submit -------------------------------------------------------------------


@router.post("", response_model=ClaimModel)
def submit_claim(
    body: _SubmitRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_claims")),
) -> ClaimModel:
    """File a new claim against a policy's member."""
    try:
        return claim_service.submit_claim(
            db,
            policy_id=body.policy_id,
            member_id=body.member_id,
            amount_claimed=body.amount_claimed,
            incident_date=body.incident_date,
            benefit_id=body.benefit_id,
            description=body.description,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post("/submit")
def submit_claim_partial(
    request: Request,
    policy_id: str = Form(...),
    member_id: str = Form(...),
    amount_claimed: str = Form(...),
    incident_date: str = Form(...),
    benefit_id: str | None = Form(None),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("view_claims")),
) -> HTMLResponse:
    """HTMX Form: file a claim and return the list partial on success."""
    try:
        claim_service.submit_claim(
            db,
            policy_id=int(policy_id),
            member_id=int(member_id),
            amount_claimed=float(amount_claimed),
            incident_date=dt.date.fromisoformat(incident_date),
            benefit_id=int(benefit_id) if benefit_id else None,
            description=description,
        )
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='alert alert-danger'>{exc}</div>", status_code=400
        )
    claims = claim_service.list_claims(db, policy_id=int(policy_id))
    return templates.TemplateResponse(
        request,
        "partials/claim_list.html",
        {
            "claims": claims,
            "can_manage": _has_permission(user, "manage_claims"),
            "view_claims": _has_permission(user, "view_claims"),
            "policies": list_policies(db),
            "today": dt.date.today(),
        },
    )


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
    """HTMX partial: a single claim's detail with adjudication buttons."""
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


# --- Adjudicate (status change) ----------------------------------------------


@router.post("/{claim_id}/status", response_model=ClaimModel)
def update_claim_status(
    claim_id: int,
    body: _StatusRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_claims")),
) -> ClaimModel:
    """Change a claim's status (an underwriter action)."""
    try:
        return claim_service.update_claim_status(
            db,
            claim_id=claim_id,
            status=body.status,
            amount_approved=body.amount_approved,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post("/{claim_id}/status-form")
def update_claim_status_form(
    request: Request,
    claim_id: int,
    to_status: str = Form(...),
    amount_approved: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_claims")),
) -> HTMLResponse:
    """HTMX Form: change a claim's status and return the detail partial."""
    try:
        claim_service.update_claim_status(
            db,
            claim_id=claim_id,
            status=to_status,
            amount_approved=float(amount_approved) if amount_approved else None,
        )
    except ValueError as exc:
        return HTMLResponse(
            f"<div class='alert alert-danger'>{exc}</div>", status_code=400
        )
    claim = claim_service.get_claim(db, claim_id)
    return templates.TemplateResponse(
        request,
        "partials/claim_detail.html",
        {"claim": claim, "can_manage": True},
    )
