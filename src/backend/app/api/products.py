"""Product catalog endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role, require_user
from app.api.auth import User
from app.core.database import get_db
from app.services.products import add_product, list_products
from app.view import templates

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductModel(BaseModel):
    id: int
    name: str
    product_type: str
    description: str | None = None


@router.get("", response_model=list[ProductModel])
def list_products_endpoint(
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_products")),
) -> list[ProductModel]:
    return list_products(db)


@router.get("/list")
def product_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> HTMLResponse:
    products = list_products(db)
    return templates.TemplateResponse(
        request,
        "partials/product_list.html",
        {"products": products, "manage_products": _has_permission(user, "manage_products")},
    )


@router.post("/create")
def product_create(
    request: Request,
    name: str = Form(...),
    product_type: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_products")),
) -> HTMLResponse:
    add_product(db, name=name, product_type=product_type, description=description or None)
    return templates.TemplateResponse(
        request,
        "partials/product_list.html",
        {"products": list_products(db)},
    )
