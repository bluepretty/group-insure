"""Reference / lookup tables.

Reference data (party types, party roles, policy statuses) used to live
exclusively in ``app.enums``. These tables are the runtime-backed source of
truth for the *value set* of each, so the super-admin can add or disable a
value through CRUD rather than a code change. The finite-value-set column
remains a ``String`` (``create_all`` does not turn them into SQL enums) and the
transition map still lives in ``app.enums`` — the table holds the *values* and
their metadata, the enum still holds the *state rules*.

Every row is keyed by a string ``code`` (matching the spelling the domain has
always used — ``individual``, ``policy_holder``, ``active`` …) rather than an
auto id, so the code itself is a stable identifier a caller can name.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Association: a party holds one or more roles (many-to-many). A party can be
# both a broker and a policyholder, so the legacy single-column ``party_type``
# (which only ever held one of {policyholder, broker}) is insufficient — hence
# this join table keyed on the role's ``code``.
party_role_association = Table(
    "party_party_roles",
    Base.metadata,
    Column("party_id", ForeignKey("parties.id", ondelete="CASCADE"), primary_key=True),
    Column("role_code", ForeignKey("party_roles.code", ondelete="CASCADE"), primary_key=True),
)


class Lookup(Base):
    """Base for every code-keyed lookup row.

    ``code`` is a string primary key matching the domain's spelling so lookup
    tables double as the value-set definition. ``is_active`` soft-disables a row
    (deactivate rather than delete, to keep the audit trail intact), and
    ``sort_order`` controls display ordering in the admin UI.
    """

    __abstract__ = True

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class PartyType(Lookup):
    __tablename__ = "party_types"


class PartyRole(Lookup):
    __tablename__ = "party_roles"


class PolicyStatus(Lookup):
    __tablename__ = "policy_statuses"


class Position(Lookup):
    """A role a person holds within a policyholder organization.

    ``positions.code`` is what ``member.position_code`` references — the roster
    label (``staff``, ``director`` …) used to group members for reporting.
    """

    __tablename__ = "positions"


class Relationship(Lookup):
    """A kinship a member has to the policyholder (``self``, ``spouse`` …).

    ``relationships.code`` is what ``member.relationship_code`` references.
    """

    __tablename__ = "relationships"
