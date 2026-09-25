"""Invoice: a billing artifact issued against a policy for its computed premium.

``total_amount`` snapshots the policy premium at issue time so the invoice is a
stable record even if the policy's premiums change afterward; ``paid_amount``
tracks money received. Invoice ``status`` is reconciled from ``paid_amount``.
"""
import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("policies.id"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(String(20))
    # "issued" | "partially_paid" | "paid" | "written_off"
    status: Mapped[str] = mapped_column(String(20), default="issued")
    total_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    paid_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    issued_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    paid_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
