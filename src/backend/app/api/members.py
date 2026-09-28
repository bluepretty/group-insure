"""Member CRUD endpoints and HTMX partials."""
import datetime as dt

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import User, _has_permission, require_role
from app.core.database import get_db
from app.models.member import Member
from app.services.audit import record_log
from app.services.benefits import list_benefits
from app.services.census import census_add, census_remove
from app.services.lookup import list_lookup
from app.services.members import (
    enroll_member,
    list_members,
    terminate_member,
    update_member,
    member_usage,
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
    relationship_code: str | None = None
    position_code: str | None = None
    annual_salary: float | None = None


@router.get("", response_model=list[MemberModel])
def list_members_endpoint(
    db: Session = Depends(get_db),
    party_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
    _: None = Depends(require_role("view_members")),
) -> list[MemberModel]:
    return list_members(db, party_id=party_id, limit=limit, offset=offset)


@router.get("/list")
def member_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("view_members")),
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
            "relationships": list_lookup(db, "relationships"),
            "positions": list_lookup(db, "positions"),
            "today": dt.date.today(),
            "manage_members": _has_permission(user, "manage_members"),
        },
    )


@router.get("/{member_id}")
def get_member_endpoint(
    member_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_members")),
) -> JSONResponse:
    """Return one member as JSON so the edit modal can pre-fill its fields."""
    target = db.get(Member, member_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Member not found"})
    return JSONResponse(
        content={
            "id": target.id,
            "first_name": target.first_name,
            "last_name": target.last_name,
            "relationship_code": target.relationship_code or "",
            "position_code": target.position_code or "",
            "annual_salary": float(target.annual_salary) if target.annual_salary is not None else None,
        }
    )


@router.put("/{member_id}")
def edit_member(
    member_id: int,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_code: str | None = Form(None),
    position_code: str | None = Form(None),
    annual_salary: float | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> JSONResponse:
    target = db.get(Member, member_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Member not found"})
    update_member(
        db,
        member=target,
        first_name=first_name,
        last_name=last_name,
        relationship_code=relationship_code or None,
        position_code=position_code or None,
        annual_salary=annual_salary,
    )
    record_log(
        db,
        action="member_edit",
        actor_id=None,
        entity="Member",
        entity_id=target.id,
    )
    return JSONResponse(
        content={
            "id": target.id,
            "first_name": target.first_name,
            "last_name": target.last_name,
            "relationship_code": target.relationship_code or "",
            "position_code": target.position_code or "",
            "annual_salary": float(target.annual_salary) if target.annual_salary is not None else None,
        }
    )


@router.post("/create")
def member_create(
    request: Request,
    policy_id: int = Form(...),
    party_id: int | None = Form(None),
    organization_id: int | None = Form(None),
    member_number: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_code: str | None = Form(None),
    position_code: str | None = Form(None),
    annual_salary: float | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> HTMLResponse:
    try:
        enroll_member(
            db,
            policy_id=policy_id,
            party_id=party_id,
            organization_id=organization_id,
            member_number=member_number,
            first_name=first_name,
            last_name=last_name,
            relationship_code=relationship_code or None,
            position_code=position_code or None,
            annual_salary=annual_salary,
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
    relationship_code: str | None = Form(None),
    position_code: str | None = Form(None),
    annual_salary: float | None = Form(None),
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
            relationship_code=relationship_code or None,
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
        # In-use guard: a member that has open claims or a benefit election
        # cannot be removed without orphaning those rows.
        usage = member_usage(db, member_id)
        if not usage["ok"]:
            reasons = []
            if usage["claims"]:
                reasons.append(f"{usage['claims']} claim(s)")
            if usage["elections"]:
                reasons.append(f"{usage['elections']} benefit election(s)")
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Cannot remove member: " + ", ".join(reasons)
                    + " reference it."
                },
            )
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
