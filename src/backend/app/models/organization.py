"""Organization: a tenant/agent that owns Parties and policies.

Kept lightweight for now — an Organization scopes Party data. The insurer,
each broker, and (later) each large policyholder can run an org.
"""
import datetime as dt

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # "insurer" | "broker" | "policyholder"
    type: Mapped[str] = mapped_column(String(50), default="insurer")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
