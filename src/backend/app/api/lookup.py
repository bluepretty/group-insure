"""Reference/lookup CRUD endpoints.

The reference/lookup tables (``party_types``, ``party_roles``,
``policy_statuses``) are admin-managed data: only the super-admin (the role that
holds ``manage_references``) may create or edit a value, while any authenticated
user may read them — underwriters and brokers look these values up to validate
parties and policies, but they must never mutate the value set.

The router is path-parameterised on ``{kind}`` (one of ``party_types``,
``party_roles``, ``policy_statuses``) and ``{code}`` (the value's string key),
so a single set of handlers covers all three tables. ``kind`` is validated
against the known kinds in the service layer: an unknown kind raises
``ValueError`` and surfaces as a 400, so ``/api/lookup/not_a_table/`` can never
reach an arbitrary table.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.auth import require_role, require_user
from app.core.database import get_db
from app.models.user import User
from app.services.audit import record_log
from app.services.lookup import (
    _model_class,
    add_lookup,
    deactivate_lookup,
    get_lookup,
    list_lookup,
    lookup_usage,
    update_lookup,
)

router = APIRouter(prefix="/api/lookup", tags=["lookup"])

MANAGE_PERMISSION = "manage_references"


def _row_view(row) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
    }


def _dispatch_create_error(exc: ValueError) -> JSONResponse:
    """Map a service ``ValueError`` from a create onto the right status code.

    "Already exists" is a 409 (conflict); every other validation failure
    (empty name, an unknown code for a closed kind) is a 400.
    """
    detail = str(exc) or "Validation error"
    status = 409 if "already exists" in detail.lower() else 400
    return JSONResponse(status_code=status, content={"detail": detail})


# --- List / get -----------------------------------------------------------------


@router.get("/{kind}")
def list_lookup_endpoint(
    kind: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_user),
) -> JSONResponse:
    """List active values for one kind.

    An unknown ``kind`` raises ``ValueError`` (→ 400) rather than returning an
    empty list, so a mistyped kind is an error, not silence.
    """
    try:
        rows = list_lookup(db, kind)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"kind": kind, "values": [_row_view(r) for r in rows]})


@router.get("/{kind}/{code}")
def get_lookup_endpoint(
    kind: str,
    code: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_user),
) -> JSONResponse:
    """Fetch one active value, or 404 if absent/inactive/such a kind."""
    row = get_lookup(db, kind, code)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return JSONResponse(content=_row_view(row))


# --- Create ---------------------------------------------------------------------


@router.post("/{kind}", response_model=dict)
def create_lookup(
    kind: str,
    code: str = Form(...),
    name: str = Form(""),
    description: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(MANAGE_PERMISSION)),
) -> JSONResponse:
    """Create a value in one kind (super-admin only).

    ``code`` is the primary key (a stable identifier the domain uses);
    ``name`` is the human label. 409 if the code already exists; 400 for an
    empty name or an unknown code on a closed kind (e.g. inventing a new policy
    status). ``name`` defaults to empty so the service can turn an empty value
    into a 400 rather than Starlette's 422.
    """
    try:
        row = add_lookup(
            db,
            kind=kind,
            code=code,
            name=name,
            description=description or None,
            sort_order=sort_order,
        )
    except ValueError as exc:
        return _dispatch_create_error(exc)
    record_log(
        db,
        action=f"{kind}_created",
        actor_id=user.id,
        entity=f"{kind[:-1].title()}",
        details=f"code={code}",
    )
    db.commit()
    return JSONResponse(status_code=201, content=_row_view(row))


# --- Update ---------------------------------------------------------------------


@router.put("/{kind}/{code}", response_model=dict)
def update_lookup_endpoint(
    kind: str,
    code: str,
    name: str = Form(""),
    description: str = Form(""),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(MANAGE_PERMISSION)),
) -> JSONResponse:
    """Update a value's metadata, or 404 if absent/inactive/such a kind."""
    row = get_lookup(db, kind, code)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    try:
        update_lookup(
            db,
            row,
            kind=kind,
            name=name,
            description=description or None,
            sort_order=sort_order,
            is_active=is_active,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    record_log(
        db,
        action=f"{kind}_updated",
        actor_id=user.id,
        entity=f"{kind[:-1].title()}",
        entity_id=row.code,
    )
    db.commit()
    return JSONResponse(content=_row_view(row))


# --- Deactivate -----------------------------------------------------------------


@router.delete("/{kind}/{code}", response_model=dict)
def deactivate_lookup_endpoint(
    kind: str,
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(MANAGE_PERMISSION)),
) -> JSONResponse:
    """Soft-disable a value (keep the row for audit).

    400 if ``kind`` is not a known lookup table (so ``/api/lookup/not_a_table/``
    cannot masquerade as a missing row); 409 with a reason if business records
    still reference it (e.g. a policy status an active policy holds, or a
    party_type a party declares); 200 otherwise. The row stays in the DB.
    """
    # Reject an unknown kind as a 400 (bad request) rather than a 404, so the
    # endpoint can never be confused with "row not found" — ``get_lookup``
    # swallows the ValueError for unknown kinds on purpose for reads, but a
    # write against a table that does not exist is a client error.
    try:
        _model = _model_class(kind)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    row = get_lookup(db, kind, code)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    usage = lookup_usage(db, kind, code)
    if not usage["ok"]:
        field = "policies" if kind == "policy_statuses" else "parties"
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"Cannot deactivate: {usage[field]} {field} still use it",
            },
        )
    deactivate_lookup(db, row)
    record_log(
        db,
        action=f"{kind}_deactivated",
        actor_id=user.id,
        entity=f"{kind[:-1].title()}",
        entity_id=row.code,
    )
    db.commit()
    return JSONResponse(content={"code": code, "is_active": False})
