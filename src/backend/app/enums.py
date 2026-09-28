"""Enumerated value sets used across the domain.

These are the single source of truth for the finite string values a status,
type, or category column may hold. The database columns remain ``String`` (they
were created before this module and migrating to real SQL enums would require a
migration that ``Base.metadata.create_all`` doesn't run); these enums give the
values a home in one place so models, services, and schema validation all point
at the same definitions rather than re-declaring them inline.

Keeping the transition map here too means a new transition is a change in one
spot, validated by one place.
"""
from __future__ import annotations

from typing import FrozenSet


class PolicyStatus:
    """Policy lifecycle. ``closed`` is terminal; ``draft`` only goes active."""

    DRAFT = "draft"
    ACTIVE = "active"
    LAPSED = "lapsed"
    CLOSED = "closed"

    ALL: frozenset[str] = frozenset(
        {DRAFT, ACTIVE, LAPSED, CLOSED}
    )

    # Map each status to the set of statuses it may transition into. Mirrors the
    # rules enforced in ``services.policies``: active -> draft is not allowed.
    TRANSITIONS: dict[str, FrozenSet[str]] = {
        DRAFT: frozenset({ACTIVE}),
        ACTIVE: frozenset({LAPSED}),
        LAPSED: frozenset({ACTIVE, CLOSED}),
        CLOSED: frozenset(),
    }


class ClaimStatus:
    """Claim lifecycle. ``approved`` and ``rejected`` are decision states; both
    ``paid`` and ``rejected`` are terminal."""

    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"

    ALL: frozenset[str] = frozenset({SUBMITTED, APPROVED, REJECTED, PAID})

    TRANSITIONS: dict[str, FrozenSet[str]] = {
        SUBMITTED: frozenset({APPROVED, REJECTED}),
        APPROVED: frozenset({PAID}),
        REJECTED: frozenset(),
        PAID: frozenset(),
    }


class InvoiceStatus:
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    WRITTEN_OFF = "written_off"

    ALL: frozenset[str] = frozenset({ISSUED, PARTIALLY_PAID, PAID, WRITTEN_OFF})


class PaymentStatus:
    POSTED = "posted"
    VOID = "void"

    ALL: frozenset[str] = frozenset({POSTED, VOID})


class MemberStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"

    ALL: frozenset[str] = frozenset({ACTIVE, INACTIVE, TERMINATED})


class PartyType:
    """A Party is either a policyholder (employer/association) or a broker."""

    POLICYHOLDER = "policyholder"
    BROKER = "broker"

    ALL: frozenset[str] = frozenset({POLICYHOLDER, BROKER})


class ProductType:
    """Catalog product category (e.g. ``group-term-life``)."""

    GROUP_TERM_LIFE = "group-term-life"
    GROUP_DISABILITY = "group-disability"
    GROUP_HEALTH = "group-health"

    ALL: frozenset[str] = frozenset(
        {GROUP_TERM_LIFE, GROUP_DISABILITY, GROUP_HEALTH}
    )


def validate_transition(current: str, target: str, transitions: dict) -> None:
    """Raise ``ValueError`` if ``current -> target`` is not a legal transition.

    Used by service-layer transition guards. Unknown values raise too, so a
    stale string on an existing row is surfaced rather than silently accepted.
    """
    if current not in transitions:
        raise ValueError(f"Unknown status: {current!r}")
    if target not in transitions:
        raise ValueError(f"Unknown status: {target!r}")
    allowed = transitions[current]
    if target not in allowed:
        valid = ", ".join(sorted(allowed)) or "none (terminal)"
        raise ValueError(
            f"Cannot transition status from {current!r} to {target!r}; "
            f"allowed: {valid}"
        )
