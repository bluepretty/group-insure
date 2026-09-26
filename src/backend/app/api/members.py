"""Member CRUD endpoints and HTMX partials."""
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.services.benefits import list_benefits
from app.services.census import census_add, census_remove
from app.services.members import (
    enroll_member,
    list_members,
    terminate_member,
)
from app.services.policies import list_policies
from app.view import templates

router = APIRouter(prefix="/api/members", tags=["members"])


class MemberModel(BaseModel):
    id: int
    policy_id: int
    party_id: int | None = None
    member_number: str
    first_name: str
    last_name: str
    status: str
    relationship: str | None = None


@router.get("", response_model=list[MemberModel])
def list_members_endpoint(
    db: Session = Depends(get_db),
    party_id: int | None = None,
    _: None = Depends(require_role("view_members")),
) -> list[MemberModel]:
    return list_members(db, party_id=party_id)


@router.get("/list")
def member_list(
    request: Request,
    db: Session = Depends(get_db),
    party_id: int | None = None,
) -> HTMLResponse:
    members = list_members(db, party_id=party_id)
    return templates.TemplateResponse(
        request,
        "partials/member_list.html",
        {
            "members": members,
            "policies": list_policies(db),
            "benefits": list_benefits(db),
            "today": dt.date.today(),
        },
    )


@router.post("/create")
def member_create(
    request: Request,
    policy_id: int = Form(...),
    party_id: int | None = Form(None),
    member_number: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> HTMLResponse:
    try:
        enroll_member(
            db,
            policy_id=policy_id,
            party_id=party_id,
            member_number=member_number,
            first_name=first_name,
            last_name=last_name,
            relationship=relationship or None,
        )
    except ValueError as exc:
        # Surface a friendly message back into the partial rather than a 500.
        return templates.TemplateResponse(
            request,
            "partials/member_list.html",
            {"members": list_members(db, party_id=party_id), "error": str(exc)},
        )
    return templates.TemplateResponse(
        request,
        "partials/member_list.html",
        {"members": list_members(db, party_id=party_id)},
    )


@router.post("/{member_id}/terminate")
def member_terminate(
    member_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> JSONResponse:
    try:
        member = terminate_member(db, member_id=member_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={"member_id": member.id, "status": member.status}
    )


@router.post("/{policy_id}/add")
def member_add(
    request: Request,
    policy_id: int,
    member_number: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship: str = Form(""),
    benefit_id: int | None = Form(None),
    election_amount: float | None = Form(None),
    effective_date: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> HTMLResponse:
    """Enroll a member/dependent mid-cycle, prorating the premium and billing it.

    Returns the member-list partial so the HTMX add form stays in sync, plus the
    census summary (event, effective date, proration, adjustment invoice) in the
    template context for the caller to surface.
    """
    effective = dt.date.fromisoformat(effective_date) if effective_date else dt.date.today()
    try:
        summary = census_add(
            db,
            policy_id=policy_id,
            member_number=member_number,
            first_name=first_name,
            last_name=last_name,
            effective_date=effective,
            relationship=relationship or None,
            benefit_id=benefit_id,
            election_amount=election_amount,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "partials/member_list.html",
            {"members": list_members(db, party_id=None), "error": str(exc)},
        )
    return templates.TemplateResponse(
        request,
        "partials/member_list.html",
        {"members": list_members(db, party_id=None), "summary": summary},
    )


@router.post("/{member_id}/remove")
def member_remove(
    request: Request,
    member_id: int,
    effective_date: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> HTMLResponse:
    """Terminate a member mid-cycle, prorating and crediting the premium.

    Returns the member-list partial plus the census summary (event, effective
    date, credit amount, adjustment invoice) in the ``data-summary`` attribute.
    """
    effective = dt.date.fromisoformat(effective_date) if effective_date else dt.date.today()
    try:
        summary = census_remove(db, member_id=member_id, effective_date=effective)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "partials/member_list.html",
            {"members": list_members(db, party_id=None), "error": str(exc)},
        )
    return templates.TemplateResponse(
        request,
        "partials/member_list.html",
        {"members": list_members(db, party_id=None), "summary": summary},
    )
