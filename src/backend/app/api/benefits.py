"""Benefit catalog + member-coverage election endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.core.database import get_db
from app.services.benefits import (
    add_benefit,
    elect_benefit,
    list_benefits,
    list_member_benefits,
)
from app.services.products import list_products
from app.view import templates

router = APIRouter(prefix="/api/benefits", tags=["benefits"])


class BenefitModel(BaseModel):
    id: int
    product_id: int
    code: str
    name: str
    description: str | None = None
    benefit_type: str | None = None
    coverage_amount: float | None = None


@router.get("", response_model=list[BenefitModel])
def list_benefits_endpoint(
    db: Session = Depends(get_db),
    product_id: int | None = None,
    _: None = Depends(require_role("view_benefits")),
) -> list[BenefitModel]:
    return list_benefits(db, product_id=product_id)


@router.get("/coverage", response_model=list[BenefitModel])
def member_coverage(
    db: Session = Depends(get_db),
    member_id: int | None = None,
    _: None = Depends(require_role("view_benefits")),
) -> list[BenefitModel]:
    elections = list_member_benefits(db, member_id=member_id)
    return [
        BenefitModel.model_validate(
            {
                "id": e.benefit_id,
                "product_id": e.benefit.product_id,
                "code": e.benefit.code,
                "name": e.benefit.name,
                "description": e.benefit.description,
                "benefit_type": e.benefit.benefit_type,
                "coverage_amount": e.benefit.coverage_amount,
            }
        )
        for e in elections
    ]


@router.get("/coverage-partial")
def member_coverage_partial(
    request: Request,
    db: Session = Depends(get_db),
    member_id: int | None = None,
    _: None = Depends(require_role("view_benefits")),
) -> HTMLResponse:
    elections = list_member_benefits(db, member_id=member_id)
    return templates.TemplateResponse(
        request,
        "partials/member_coverage.html",
        {"elections": elections},
    )


@router.get("/list")
def benefit_list(
    request: Request,
    db: Session = Depends(get_db),
    product_id: int | None = None,
) -> HTMLResponse:
    benefits = list_benefits(db, product_id=product_id)
    return templates.TemplateResponse(
        request,
        "partials/benefit_list.html",
        {"benefits": benefits, "products": list_products(db)},
    )


@router.post("/add")
def benefit_add(
    request: Request,
    product_id: int = Form(...),
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    benefit_type: str = Form(""),
    coverage_amount: float | None = Form(None),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_benefits")),
) -> HTMLResponse:
    try:
        add_benefit(
            db,
            product_id=product_id,
            code=code,
            name=name,
            description=description or None,
            benefit_type=benefit_type or None,
            coverage_amount=coverage_amount,
        )
    except ValueError as exc:
        # Surface a friendly message back into the partial rather than a 500.
        return templates.TemplateResponse(
            request,
            "partials/benefit_list.html",
            {
                "benefits": list_benefits(db, product_id=product_id),
                "error": str(exc),
                "products": list_products(db),
            },
        )
    return templates.TemplateResponse(
        request,
        "partials/benefit_list.html",
        {"benefits": list_benefits(db, product_id=product_id), "products": list_products(db)},
    )


@router.post("/{member_id}/elect")
def benefit_elect(
    request: Request,
    member_id: int,
    benefit_id: int = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_members")),
) -> JSONResponse:
    try:
        member_benefit = elect_benefit(db, member_id=member_id, benefit_id=benefit_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(
        content={
            "member_id": member_id,
            "benefit_id": benefit_id,
            "election_amount": member_benefit.election_amount,
        }
    )
