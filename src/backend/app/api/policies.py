"""Policy CRUD endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, get_current_user, require_role
from app.models import Policy, User
from app.core.database import get_db
from app.services.invoices import list_invoices, _outstanding_invoice
from app.services.policies import (
    add_policy,
    change_policy_status,
    laps_if_overdue,
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
    user: User = Depends(get_current_user),
) -> HTMLResponse:
    policies = list_policies(db, party_id=party_id)
    invoices = {
        p.id: list_invoices(db, policy_id=p.id) for p in policies
    }
    outstanding = {
        p.id: _outstanding_invoice(db, policy_id=p.id) for p in policies
    }
    return templates.TemplateResponse(
        request,
        "partials/policy_list.html",
        {
            "policies": policies,
            "products": list_products(db),
            "invoices": invoices,
            "outstanding": outstanding,
            "can_manage": _has_permission(user, "manage_policies"),
        },
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
    policies = list_policies(db)
    return templates.TemplateResponse(
        request,
        "partials/policy_list.html",
        {
            "policies": policies,
            "can_manage": True,
            "outstanding": {
                p.id: _outstanding_invoice(db, policy_id=p.id) for p in policies
            },
            "invoices": {
                p.id: list_invoices(db, policy_id=p.id) for p in policies
            },
        },
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


@router.get("/{policy_id}/lapse-check")
def policy_lapse_check(
    policy_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_policies")),
) -> JSONResponse:
    """Evaluate (and trigger) auto-lapse for this policy's unpaid invoice.

    Returns the policy's *actual* status. The call also triggers the lapse when
    an active policy has an overdue unpaid invoice, so the response reflects the
    state after that transition.
    """
    laps_if_overdue(db, policy_id=policy_id)
    policy = db.get(Policy, policy_id)
    return JSONResponse(
        content={
            "policy_id": policy_id,
            "status": policy.status,
            "lapsed": policy.status == "lapsed",
        }
    )


@router.post("/{policy_id}/close")
def policy_close(
    policy_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_policies")),
) -> JSONResponse:
    from app.services.policies import close_policy

    try:
        policy = close_policy(db, policy_id=policy_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"policy_id": policy_id, "status": policy.status})
