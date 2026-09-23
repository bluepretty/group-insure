"""Premium pricing + allocation endpoints and HTMX partials.

Premiums are computed from a benefit's per-unit catalog rate and a member's
elected amount. A policy's premium is the sum of its member premiums.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role, require_user
from app.api.auth import User
from app.core.database import get_db
from app.models.member import Member
from app.services.benefits import set_benefit_rate, list_member_benefits
from app.services.members import list_members
from app.services.premiums import (
    per_member_premium,
    policy_premium,
    set_election_amount,
)
from app.view import templates

router = APIRouter(prefix="/api/premiums", tags=["premiums"])


class PolicyPremiumModel(BaseModel):
    policy_id: int
    total: float
    breakdown: list[dict]


class MemberPremiumModel(BaseModel):
    member_id: int
    premium: float


@router.get("/policy")
def policy_premium_endpoint(
    db: Session = Depends(get_db),
    policy_id: int | None = None,
    _: None = Depends(require_role("view_premiums")),
) -> PolicyPremiumModel:
    if policy_id is None:
        return JSONResponse(status_code=400, content={"detail": "policy_id required"})
    return policy_premium(db, policy_id=policy_id)


@router.get("/policy-html")
def policy_premium_partial(
    request: Request,
    db: Session = Depends(get_db),
    policy_id: int | None = None,
    _: None = Depends(require_role("view_premiums")),
) -> HTMLResponse:
    """Per-policy premium summary, rendered as an HTMX-partial.

    Rendered as an HTMX-partial and swapped into ``#content`` from a policy's
    "Premiums" action. A policy with no enrolled elections renders an "empty"
    summary rather than an error.
    """
    if policy_id is None:
        return JSONResponse(status_code=400, content={"detail": "policy_id required"})
    try:
        summary = policy_premium(db, policy_id=policy_id)
    except ValueError:
        return HTMLResponse("<p class='text-muted'>Policy not found.</p>")
    return templates.TemplateResponse(
        request,
        "partials/policy_premium.html",
        {"summary": summary},
    )


@router.get("/member")
def member_premium_endpoint(
    db: Session = Depends(get_db),
    member_id: int | None = None,
    _: None = Depends(require_role("view_premiums")),
) -> MemberPremiumModel:
    if member_id is None:
        return JSONResponse(status_code=400, content={"detail": "member_id required"})
    return MemberPremiumModel(
        member_id=member_id,
        premium=float(per_member_premium(db, member_id=member_id)),
    )


@router.get("/detail")
def premium_detail_partial(
    request: Request,
    db: Session = Depends(get_db),
    member_id: int | None = None,
    user: User = Depends(require_user),
    _: None = Depends(require_role("view_premiums")),
) -> HTMLResponse:
    """Per-member election + premium detail, with an amount-edit form.

    Rendered as an HTMX-partial and swapped into ``#content``. ``member_id`` is
    required because a member premium only exists once elected.
    """
    if member_id is None:
        members = list_members(db)
        return templates.TemplateResponse(
            request,
            "partials/premium_picker.html",
            {"members": members},
        )
    member = db.get(Member, member_id)
    if member is None:
        return HTMLResponse("<p class='text-muted'>Member not found.</p>")
    elections = list_member_benefits(db, member_id=member_id)
    election = elections[0] if elections else None
    premium = 0.0
    if election is not None:
        try:
            premium = float(per_member_premium(db, member_id=member_id))
        except ValueError:
            premium = 0.0
    return templates.TemplateResponse(
        request,
        "partials/premium_detail.html",
        {
            "member": member,
            "election": election,
            "premium": premium,
            "can_manage": _has_permission(user, "manage_premiums")
        },
    )


@router.get("/detail-json")
def premium_detail_json(
    request: Request,
    db: Session = Depends(get_db),
    member_id: int | None = None,
    _: None = Depends(require_role("view_premiums")),
) -> JSONResponse:
    if member_id is None:
        return JSONResponse(status_code=400, content={"detail": "member_id required"})
    member = db.get(Member, member_id)
    if member is None:
        return JSONResponse(status_code=404, content={"detail": "Member not found"})
    return JSONResponse(
        content={
            "member_id": member_id,
            "premium": float(per_member_premium(db, member_id=member_id)),
        }
    )


@router.post("/elect-amount")
def set_elect_amount(
    request: Request,
    member_id: int = Form(...),
    amount: float = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_premiums")),
) -> JSONResponse:
    try:
        set_election_amount(db, member_id=member_id, amount=amount)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={
            "member_id": member_id,
            "premium": float(per_member_premium(db, member_id=member_id)),
        }
    )


@router.post("/rate")
def set_rate(
    request: Request,
    benefit_id: int = Form(...),
    premium_rate: float = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_benefits")),
) -> JSONResponse:
    try:
        set_benefit_rate(db, benefit_id=benefit_id, premium_rate=premium_rate)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"benefit_id": benefit_id, "premium_rate": premium_rate})
