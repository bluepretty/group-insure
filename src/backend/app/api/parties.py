"""Party CRUD endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role, require_user
from app.api.auth import User
from app.core.database import get_db
from app.models.party import Party
from app.services.audit import record_log
from app.services.parties import add_party, get_party, list_parties, party_usage, update_party
from app.view import templates

router = APIRouter(prefix="/api/parties", tags=["parties"])


class PartyModel(BaseModel):
    id: int | None = None
    name: str
    party_type: str
    email: str | None = None
    broker_id: int | None = None
    organization_id: int | None = None


@router.get("", response_model=list[PartyModel])
def list_parties_endpoint(
    db: Session = Depends(get_db), _=Depends(require_role("manage_parties"))
) -> list[PartyModel]:
    return list_parties(db)


@router.post("", response_model=dict)
def create_party(
    payload: PartyModel,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_parties")),
) -> dict:
    try:
        party = add_party(
            db,
            name=payload.name,
            party_type=payload.party_type,
            email=payload.email,
            broker_id=payload.broker_id,
            organization_id=payload.organization_id,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return {"id": party.id, "name": party.name}


@router.get("/list")
def party_list(request: Request, db: Session = Depends(get_db), _: User = Depends(require_user)) -> HTMLResponse:
    parties = list_parties(db)
    return templates.TemplateResponse(
        request,
        "partials/party_list.html",
        {"parties": parties, "manage_parties": _has_permission(_, "manage_parties")},
    )


@router.post("/create")
def party_create(
    request: Request,
    name: str = Form(...),
    party_type: str = Form(...),
    email: str | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_parties")),
) -> HTMLResponse:
    try:
        party = add_party(db, name=name, party_type=party_type, email=email)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return templates.TemplateResponse(
        request,
        "partials/party_list.html",
        {"parties": list_parties(db)},
    )


@router.get("/{party_id}", response_model=dict)
def get_party_endpoint(
    party_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_parties")),
) -> dict | JSONResponse:
    """API: one party, for pre-filling the edit modal."""
    target = list_parties(db, active_only=False)
    target = next((p for p in target if p.id == party_id), None)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Party not found"})
    return {
        "id": target.id,
        "name": target.name,
        "party_type": target.party_type,
        "email": target.email,
        "active": target.active,
    }


@router.put("/{party_id}")
def edit_party(
    party_id: int,
    request: Request,
    name: str = Form(...),
    party_type: str = Form(...),
    email: str | None = Form(None),
    active: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_parties")),
) -> JSONResponse:
    target = db.get(Party, party_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Party not found"})
    try:
        update_party(db, target, name=name, party_type=party_type, email=email, active=active)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    record_log(db, action="party_edited", actor_id=user.id, entity="Party", entity_id=target.id)
    return JSONResponse(content={"id": target.id, "name": target.name})


@router.delete("/{party_id}")
def delete_party(
    party_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_parties")),
) -> JSONResponse:
    """Soft-delete a party (set active=False), unless still referenced.

    409 with a reason if an active policy/member still points at this party;
    200 ({"ok": true}) otherwise. The row stays in the DB (audit trail).
    """
    target = db.get(Party, party_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Party not found"})
    usage = party_usage(db, party_id)
    if not usage["ok"]:
        reasons = []
        if usage["policies"]:
            reasons.append(f"{usage['policies']} active policies reference this party")
        if usage["members"]:
            reasons.append(f"{usage['members']} active members reference this party")
        return JSONResponse(
            status_code=409,
            content={"detail": "Cannot deactivate party: " + ", ".join(reasons)},
        )
    update_party(db, party=target, active=False)
    record_log(db, action="party_deleted", actor_id=user.id, entity="Party", entity_id=target.id)
    return JSONResponse(content={"ok": True})
