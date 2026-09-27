"""Product catalog helpers."""
from sqlalchemy import select

from app.models.product import Product
from app.services.audit import record_log


def list_products(
    db,
    *,
    active_only: bool = False,
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
