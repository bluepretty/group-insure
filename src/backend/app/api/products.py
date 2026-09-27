"""Product catalog endpoints and HTMX partials."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role, require_user
from app.api.auth import User
from app.core.database import get_db
from app.models.product import Product
from app.services.audit import record_log
from app.services.products import add_product, list_products, product_usage, update_product
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
    limit: int | None = None,
    offset: int | None = None,
    _: None = Depends(require_role("view_products")),
) -> list[ProductModel]:
    return list_products(db, limit=limit, offset=offset)


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


@router.get("/{product_id}", response_model=dict)
def get_product_endpoint(
    product_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("view_products")),
) -> dict | JSONResponse:
    """API: one product, for pre-filling the edit modal."""
    product = db.get(Product, product_id)
    if not product:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})
    return {
        "id": product.id,
        "name": product.name,
        "product_type": product.product_type,
        "description": product.description,
        "is_active": product.is_active,
    }


@router.put("/{product_id}")
def edit_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    product_type: str = Form(...),
    description: str | None = Form(None),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_products")),
) -> JSONResponse:
    target = db.get(Product, product_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})
    update_product(db, product=target, name=name, product_type=product_type, description=description or None, is_active=is_active)
    record_log(db, action="product_edited", actor_id=user.id, entity="Product", entity_id=target.id)
    return JSONResponse(content={"id": target.id, "name": target.name})


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_products")),
) -> JSONResponse:
    """Soft-delete a product (set is_active=False), unless it is still referenced.

    409 with a reason if an active policy still references this product;
    200 ({"ok": true}) otherwise. The row stays in the DB (audit trail).
    """
    target = db.get(Product, product_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})
    usage = product_usage(db, product_id)
    if not usage["ok"]:
        reasons = []
        if usage["policies"]:
            reasons.append(f"{usage['policies']} active policies reference this product")
        return JSONResponse(
            status_code=409,
            content={"detail": "Cannot deactivate product: " + ", ".join(reasons)},
        )
    update_product(db, product=target, is_active=False)
    record_log(db, action="product_deleted", actor_id=user.id, entity="Product", entity_id=target.id)
    return JSONResponse(content={"ok": True})
