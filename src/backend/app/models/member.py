"""Member: an individual enrolled under a group Policy.

Members are scoped to a policy (and denormalized with the policyholder party's
id so a list can filter by policyholder). Kept minimal — richer attributes come
later.
"""
import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    # Unique per policy (enforced in service layer; DB-level index on Postgres).
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
