"""Member CRUD endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
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
        {"members": members, "policies": list_policies(db)},
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
