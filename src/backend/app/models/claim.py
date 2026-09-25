"""Claim: a record raised against a policy for a covered benefit.

Claims are raised by underwriters and tracked through a small lifecycle:

    open -> under_review -> paid | denied -> closed (closed is terminal)

A claim may be tied to a specific member and, optionally, to the benefit being
claimed against. ``claim_amount`` is the admitted amount; ``paid_amount`` is the
adjudicated payout (default 0 until the underwriter adjudicates).
"""
import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id"), nullable=True
    )
    benefit_id: Mapped[int | None] = mapped_column(
        ForeignKey("benefits.id"), nullable=True
    )
    # "open" | "under_review" | "paid" | "denied" | "closed"
    status: Mapped[str] = mapped_column(String(20), default="open")
    claim_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    paid_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )
