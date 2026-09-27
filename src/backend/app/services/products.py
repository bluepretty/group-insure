"""Product catalog helpers."""
from sqlalchemy import func, select

from app.models.product import Product
from app.models.policy import Policy
from app.services.audit import record_log


def list_products(
    db,
    *,
    active_only: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Product]:
    stmt = select(Product)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    stmt = stmt.order_by(Product.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    return db.scalars(stmt).all()


def get_product(db, product_id: int) -> Product | None:
    return db.get(Product, product_id)


def add_product(
    db,
    *,
    name: str,
    product_type: str,
    description: str | None = None,
    is_active: bool = True,
) -> Product:
    product = Product(
        name=name,
        product_type=product_type,
        description=description,
        is_active=is_active,
    )
    db.add(product)
    db.commit()
    record_log(db, action="product_create", entity="Product", entity_id=product.id)
    return product


def update_product(
    db,
    *,
    product: Product,
    name: str | None = None,
    product_type: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> Product:
    """Update a product's mutable fields.

    Nothing is committed here so the caller can bundle the write with an audit
    log in one transaction.
    """
    if name is not None:
        product.name = name
    if product_type is not None:
        product.product_type = product_type
    if description is not None:
        product.description = description
    if is_active is not None:
        product.is_active = is_active
    return product


def product_usage(db, product_id: int) -> dict:
    """Return counts of rows that would be orphaned if ``product_id`` were
    soft-deleted. A product that an active policy still references cannot be
    removed (its FK is NOT NULL). ``{"ok": True}`` means safe to deactivate.
    """
    policies = db.scalar(
        select(func.count()).select_from(Policy).where(Policy.product_id == product_id)
    )
    return {"ok": policies == 0, "policies": policies}
