"""Party CRUD endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.services.audit import record_log
from app.services.parties import add_party, list_parties
from app.view import templates

router = APIRouter(prefix="/api/parties", tags=["parties"])


class PartyModel(BaseModel):
    name: str
    party_type: str
    email: str | None = None
    broker_id: int | None = None
    organization_id: int | None = None


@router.get("", response_model=list[PartyModel])
def list_parties_endpoint(
    db: Session = Depends(get_db), _=Depends(require_role("manage_parties"))
) -> list[PartyModel]:
    return [PartyModel.model_validate(p) for p in list_parties(db)]


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
def party_list(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    parties = list_parties(db)
    return templates.TemplateResponse(
        request,
        "partials/party_list.html",
        {"parties": parties},
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
