"""Party: a policyholder (employer/association) or a broker.

A Party optionally belongs to an Organization and can be linked to a broker
that created it. A Party carries a set of roles (many-to-many via
``party_party_roles``) — historically a single ``party_type`` column held either
``policyholder`` or ``broker``; the association table lets one party hold more
than one role (e.g. both broker and policyholder).
"""
import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.lookup import PartyRole, party_role_association


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Legacy union field: the raw code stored here is a role code
    # (``policy_holder``/``broker``, formerly ``policyholder``/``broker``) or an
    # entity-type code (``individual``/``corporation``/``trust``). Kept as a
    # String for back-compat with existing data and tests; validated by the
    # service against the lookup tables, never a hard DB FK.
    party_type: Mapped[str] = mapped_column(String(50))
    # Roles a Party holds (many-to-many). Enables a party to be both a broker
    # and a policyholder, which the legacy single-column party_type could not.
    roles: Mapped[list[PartyRole]] = relationship(
        secondary=party_role_association,
        backref="parties",
    )
    # Email is a first-class, optional field on every external record: any
    # present value is validated (validators.validate_email), but absence is
    # always allowed. Nullable on purpose so existing records and the smoke DB
    # are unaffected.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
