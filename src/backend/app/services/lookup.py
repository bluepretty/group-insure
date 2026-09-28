"""Reference/lookup CRUD helpers.

Every kind of lookup data (``party_types``, ``party_roles``, ``policy_statuses``)
is stored in its own table and managed through the same four operations: list,
get, create, update, deactivate. This module centralises that so the API layer
stays thin.

A ``code`` is a string primary key that matches the spelling the domain has
always used, so a caller can name a value directly (``policy_holder`` rather
than an opaque integer id). New codes may only be created for a known kind; the
service rejects unknown kinds so ``/api/lookup/{something_else}/`` cannot
write to an arbitrary table.

Seeding is the bootstrap that lets the app run against an empty database:
``seed_reference_data`` inserts the baseline rows for each kind if its table is
empty. It is idempotent, so it is safe to call on every startup and on every
engine creation in tests.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.lookup import (
    PartyRole,
    PartyType,
    PolicyStatus,
    Position,
    Relationship,
)

# Each kind maps to its table model. ``code``-keyed, so the value set is
# discoverable through these queries.
_KIND_MODELS: dict[str, type] = {
    "party_types": PartyType,
    "party_roles": PartyRole,
    "policy_statuses": PolicyStatus,
    "positions": Position,
    "relationships": Relationship,
}

# Baseline rows inserted by ``seed_reference_data`` when a table is empty.
# ``name`` is a human label; ``sort_order`` controls display order. These are
# the values the domain has always relied on (see ``app.enums``); the service
# layer may add more over time, but the baseline is what a fresh database ships
# with so nothing is empty on first run.
_DEFAULT_ROWS: dict[str, list[dict[str, Any]]] = {
    "party_types": [
        {"code": "individual", "name": "Individual", "sort_order": 1},
        {"code": "corporation", "name": "Corporation", "sort_order": 2},
        {"code": "trust", "name": "Trust", "sort_order": 3},
    ],
    "party_roles": [
        {"code": "policy_holder", "name": "Policyholder", "description": "The party whose coverage this role refers to.", "sort_order": 1},
        {"code": "broker", "name": "Broker", "description": "An insurance broker acting for a client.", "sort_order": 2},
        {"code": "underwriter", "name": "Underwriter", "description": "The insurer's underwriter.", "sort_order": 3},
        {"code": "member", "name": "Member", "description": "An insured member of a group policy.", "sort_order": 4},
        {"code": "beneficiary", "name": "Beneficiary", "description": "A person entitled to a benefit.", "sort_order": 5},
    ],
    "policy_statuses": [
        {"code": "draft", "name": "Draft", "description": "Not yet issued.", "sort_order": 1},
        {"code": "active", "name": "Active", "description": "In force.", "sort_order": 2},
        {"code": "lapsed", "name": "Lapsed", "description": "Cover stopped (e.g. non-payment).", "sort_order": 3},
        {"code": "closed", "name": "Closed", "description": "Terminated and no longer eligible for changes.", "sort_order": 4},
    ],
    "positions": [
        {"code": "staff", "name": "Staff", "description": "A general employee of the policyholder organization.", "sort_order": 1},
        {"code": "director", "name": "Director", "description": "A member of the organization's board.", "sort_order": 2},
        {"code": "manager", "name": "Manager", "description": "A person managing an organization or team.", "sort_order": 3},
        {"code": "trustee", "name": "Trustee", "description": "A person holding property in trust.", "sort_order": 4},
        {"code": "employee", "name": "Employee", "description": "A non-managerial employee.", "sort_order": 5},
    ],
    "relationships": [
        {"code": "self", "name": "Self", "description": "The policyholder themselves.", "sort_order": 1},
        {"code": "spouse", "name": "Spouse", "description": "A spouse or domestic partner.", "sort_order": 2},
        {"code": "child", "name": "Child", "description": "A dependent child.", "sort_order": 3},
        {"code": "dependent", "name": "Dependent", "description": "Another dependent covered under the policy.", "sort_order": 4},
    ],
}

# Kinds whose code universe is fixed: a new code may not be invented for them.
# The policy state machine (app.enums) relies on exactly these four statuses,
# so a freshly invented policy_status would have no legal transition. The
# party_types and party_roles tables are open, so admins can extend them.
_CLOSED_KINDS: dict[str, set[str]] = {
    "policy_statuses": {row["code"] for row in _DEFAULT_ROWS["policy_statuses"]},
}


def _model(kind: str) -> type:
    if kind not in _KIND_MODELS:
        raise ValueError(
            f"Unknown lookup kind: {kind!r}. "
            f"Valid kinds: {', '.join(_KIND_MODELS)}"
        )
    return _KIND_MODELS[kind]


# Alias exported for the API layer's delete handler, which needs to distinguish
# "unknown kind" (a 400, bad request) from "row not found" (a 404) — see
# ``deactivate_lookup_endpoint``. Reads keep using ``get_lookup``'s swallow;
# only the write path needs the explicit ValueError.
_model_class = _model


def seed_reference_data(db: Session) -> None:
    """Insert baseline rows into every empty lookup table.

    Idempotent: no-op if a table already has rows. Runs on startup (so a fresh
    database is never empty) and after engine creation in tests. Raises nothing;
    a single transaction covers the whole seed so a mid-seed failure rolls back.
    """
    for kind, rows in _DEFAULT_ROWS.items():
        model = _model(kind)
        if db.scalar(select(func.count()).select_from(model)):
            continue
        for row in rows:
            db.add(model(**row))
    db.commit()


def validate_kind_code(db: Session, kind: str, code: str) -> str:
    """Return ``code`` if it is an active row in ``kind``, else raise.

    The validation the party/policy integrations call so a foreign value cannot
    be written. An inactive row counts as "not found" so a deactivated value
    cannot be referenced — it would have to be re-activated, deliberately.
    """
    model = _model(kind)
    row = db.scalar(
        select(model).where(
            model.code == code,
            model.is_active.is_(True),
        )
    )
    if row is None:
        raise ValueError(f"Unknown {kind} code: {code!r}")
    return code


def list_lookup(db: Session, kind: str) -> list:
    """All active rows of ``kind``, display-ordered by ``sort_order``."""
    model = _model(kind)
    stmt = (
        select(model)
        .where(model.is_active.is_(True))
        .order_by(model.sort_order.asc(), model.code.asc())
    )
    return list(db.scalars(stmt).all())


def get_lookup(db: Session, kind: str, code: str):
    """Fetch one row by code, or ``None`` if absent/inactive/not such a kind."""
    try:
        model = _model(kind)
    except ValueError:
        return None
    return db.scalar(
        select(model).where(
            model.code == code,
            model.is_active.is_(True),
        )
    )


def add_lookup(
    db: Session,
    *,
    kind: str,
    code: str,
    name: str,
    description: str | None = None,
    is_active: bool = True,
    sort_order: int = 0,
):
    """Create a new lookup row.

    409 if the code already exists; 400 if ``name`` is empty; 400 if ``kind``
    is a closed kind (e.g. ``policy_statuses``) and ``code`` is not one of its
    allowed values — you cannot invent a brand-new policy status, since the
    state machine has no legal transition for it. Nothing is committed here so
    the caller can bundle it with an audit log in one transaction.
    """
    model = _model(kind)
    if not name.strip():
        raise ValueError(f"{kind} name must not be empty")
    existing = db.scalar(
        select(model).where(model.code == code)
    )
    if existing is not None:
        raise ValueError(f"{kind} code '{code}' already exists")
    if kind in _CLOSED_KINDS and code not in _CLOSED_KINDS[kind]:
        raise ValueError(
            f"Cannot create unknown {kind} code: {code!r}. Allowed: "
            f"{', '.join(sorted(_CLOSED_KINDS[kind]))}"
        )
    db.add(model(**{
        "code": code,
        "name": name,
        "description": description,
        "is_active": is_active,
        "sort_order": sort_order,
    }))
    # Flush (not commit) so the freshly inserted row is queryable for the
    # return value, while the caller still owns the transaction and can bundle
    # this with an audit log before committing.
    db.flush()
    return db.get(model, code)


def update_lookup(
    db: Session,
    target: Any,
    *,
    kind: str,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
):
    """Update a lookup row's mutable fields.

    Nothing is committed here so the caller can bundle the write with an audit
    log in one transaction. ``name`` is required if provided; ``is_active``
    soft-deletes a row.
    """
    if name is not None:
        if not name.strip():
            raise ValueError(f"{kind} name must not be empty")
        target.name = name
    if description is not None:
        target.description = description
    if is_active is not None:
        target.is_active = is_active
    if sort_order is not None:
        target.sort_order = sort_order
    return target


def deactivate_lookup(db: Session, target: Any) -> bool:
    """Soft-disable a lookup row. Returns True if it was active, else False."""
    was_active = bool(target.is_active)
    target.is_active = False
    return was_active


def lookup_usage(db: Session, kind: str, code: str) -> dict:
    """Counts of rows that would be orphaned if ``code`` were deactivated.

    Mirrors ``product_usage`` / ``party_usage``: a deactivated reference value
    that business records still point at would confuse the UI, so the delete
    endpoint refuses while the count is nonzero. Each kind has a different
    referencing table.
    """
    from app.models.party import Party
    from app.models.policy import Policy

    if kind == "party_types":
        count = db.scalar(
            select(func.count()).select_from(Party).where(Party.party_type == code)
        )
        return {"ok": count == 0, "parties": count}
    if kind == "policy_statuses":
        count = db.scalar(
            select(func.count()).select_from(Policy).where(Policy.status == code)
        )
        return {"ok": count == 0, "policies": count}
    if kind == "party_roles":
        from app.models.lookup import party_role_association as join
        count = db.scalar(
            select(func.count()).select_from(join).where(
                join.c.role_code == code
            )
        )
        return {"ok": count == 0, "parties": count}
    if kind in ("positions", "relationships"):
        from app.models.member import Member
        count = db.scalar(
            select(func.count()).select_from(Member).where(
                getattr(Member, f"{kind[:-1]}_code") == code
            )
        )
        return {"ok": count == 0, "members": count}
    raise ValueError(f"Unknown lookup kind: {kind!r}")
