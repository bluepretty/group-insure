"""LifeEvent: a durable, auditable record of a mid-term membership change.

A group policy's roster is never static — members are added or removed
mid-cycle (new hire, dependent born, departure). A ``LifeEvent`` is the
"why/when" trail for exactly one such change: it records the policy, the
affected member (optional — a policy-level event is possible), the trigger
``event_type``, the date coverage actually changed, who performed it, and a
free-form ``details`` blob. Pure tracking here; the billing effect is a
separate stage (proration).
"""
import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# The four trigger types this stage models. Kept small at the service layer
# (the DB just stores a string); this is documentation + a validation surface.
LIFE_EVENT_TYPES = (
    "new_member",   # a member was added mid-cycle
    "new_dependent",  # a dependent was added mid-cycle
    "member_departed",  # a member was removed mid-cycle
    "dependent_departed",  # a dependent was removed mid-cycle
)


class LifeEvent(Base):
    __tablename__ = "life_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("policies.id"), nullable=True, index=True
    )
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id"), nullable=True
    )
    # e.g. "new_member", "new_dependent", "member_departed", "dependent_departed"
    event_type: Mapped[str] = mapped_column(String(40))
    effective_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
