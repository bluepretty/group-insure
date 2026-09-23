"""Policy: a group policy held by a policyholder Party for a catalog product.

Kept minimal — policy number, the product it covers, coverage dates, status, and
a placeholder annual premium. Status changes flow through a small lifecycle.
"""
import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(80))
    product_id: Mapped[int] = mapped_column(ForeignKey("product_catalog.id"))
    party_id: Mapped[int | None] = mapped_column(
        ForeignKey("parties.id"), nullable=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    # "draft" | "active" | "lapsed" | "closed"
    status: Mapped[str] = mapped_column(String(20), default="draft")
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    premium: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    underwriter_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    product: Mapped["Product"] = relationship("Product")
