"""Party: a policyholder (employer/association) or a broker.

A Party optionally belongs to an Organization and can be linked to a broker
that created it.
"""
import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # "policyholder" | "broker"
    party_type: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(default=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    broker_id: Mapped[int | None] = mapped_column(
        ForeignKey("parties.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
