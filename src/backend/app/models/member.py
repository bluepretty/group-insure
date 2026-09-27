"""Member: an individual enrolled under a group Policy.

Members are scoped to a policy (and denormalized with the policyholder party's
id so a list can filter by policyholder). Kept minimal — richer attributes come
later.
"""
import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship as relationship_relationship
from sqlalchemy import UniqueConstraint

from app.core.database import Base


class Member(Base):
    __tablename__ = "members"

    __table_args__ = (UniqueConstraint("policy_id", "member_number", name="uq_member_policy_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id"), index=True
    )
    party_id: Mapped[int | None] = mapped_column(
        ForeignKey("parties.id"), nullable=True, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    # Unique per policy (enforced in service layer; DB-level composite unique below).
    member_number: Mapped[str] = mapped_column(String(60))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    relationship: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # "active" | "inactive" | "terminated"
    status: Mapped[str] = mapped_column(String(20), default="active")
    effective_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    termination_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    member_benefit: Mapped["MemberBenefit | None"] = relationship_relationship("MemberBenefit")
    policy: Mapped["Policy"] = relationship_relationship("Policy")
