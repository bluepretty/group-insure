"""Benefit: a benefit definition owned by a catalog product.

A product offers a set of benefits (e.g. a base term plan plus a spouse rider);
members elect among those benefits in Stage 4. Kept minimal — premium
allocation to each benefit is a later stage.
"""
import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Benefit(Base):
    __tablename__ = "benefits"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product_catalog.id"))
    # Unique per product (enforced in the service layer; DB-level index on
    # Postgres).
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "term" / "disability" / "dependent"
    benefit_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
