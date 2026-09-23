"""MemberBenefit: the single coverage election a member makes.

A benefit can be elected by many members (one benefit -> many members), but each
member elects exactly one benefit (one member -> one benefit). That one-to-one
rule is enforced by a unique index on member_id and by the service layer.
"""
import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MemberBenefit(Base):
    __tablename__ = "member_benefits"

    __table_args__ = (UniqueConstraint("member_id", name="uq_member_benefit_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    benefit_id: Mapped[int] = mapped_column(ForeignKey("benefits.id"))
    election_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    benefit: Mapped["Benefit"] = relationship("Benefit")
