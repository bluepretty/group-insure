"""Policy CRUD endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.services.policies import (
    add_policy,
    change_policy_status,
    list_policies,
)
from app.services.products import list_products
from app.view import templates

router = APIRouter(prefix="/api/policies", tags=["policies"])


class PolicyModel(BaseModel):
    id: int
    policy_number: str
    product_id: int
    party_id: int | None = None


@router.get("", response_model=list[PolicyModel])
def list_policies_endpoint(
    db: Session = Depends(get_db),
    party_id: int | None = None,
    _: None = Depends(require_role("view_policies")),
) -> list[PolicyModel]:
    return list_policies(db, party_id=party_id)


@router.get("/list")
def policy_list(
    request: Request,
    db: Session = Depends(get_db),
    party_id: int | None = None,
) -> HTMLResponse:
    policies = list_policies(db, party_id=party_id)
    return templates.TemplateResponse(
        request,
        "partials/policy_list.html",
        {"policies": policies, "products": list_products(db)},
    )


@router.post("/create")
def policy_create(
    request: Request,
    policy_number: str = Form(...),
    product_id: int = Form(...),
    party_id: int | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_policies")),
) -> HTMLResponse:
    add_policy(
        db,
        policy_number=policy_number,
        product_id=product_id,
        party_id=party_id,
    )
    return templates.TemplateResponse(
        request,
        "partials/policy_list.html",
        {"policies": list_policies(db)},
    )


@router.post("/{policy_id}/status")
def policy_status(
    policy_id: int,
    to_status: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_policies")),
) -> JSONResponse:
    try:
        change_policy_status(db, policy_id, to_status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"policy_id": policy_id, "status": to_status})
