"""Super-admin database reset.

Erases every business table and collapses ``users`` to a single super-admin
account. Restricted to the super-admin role (``admin``) via ``require_admin``,
which the professional roles cannot satisfy — an underwriter or broker is
refused with 403.

This endpoint exists to support the test stage. Business tables are deleted
row-by-row in ``reset_database``; the audit log is wiped along with them so the
endpoint stays simple and the wipe is atomic with the whole database. The
``organizations`` table is preserved (the tenant record) and every ``users``
row is dropped except the one freshly created super-admin, whose credentials
the response echoes back.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_admin, require_user
from app.api.auth import User
from app.core.database import get_db
from app.services import reset as reset_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetBody(BaseModel):
    """Optional override for the resulting super-admin credentials.

    Both fields are optional; ``reset_database`` applies its own safe defaults
    (``admin`` / ``admin``) when omitted. A password shorter than 8 characters
    is rejected there, so callers cannot lock themselves out with a typo.
    """

    username: str | None = None
    password: str | None = None


@router.post("/reset-database", response_model=dict)
def reset_database(
    body: ResetBody | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Wipe all business data and reset the database to one super-admin.

    ``require_admin`` guards this route: only the ``admin`` role can satisfy it.
    The response reports the resulting credentials so the caller can log in
    immediately after the reset.
    """
    # Forward a value only when the caller actually supplied it; otherwise leave
    # it to ``reset_database``'s own defaults (``admin`` / ``admin``). Passing an
    # explicit ``None`` here would shadow that default and insert a NULL into the
    # NOT NULL ``username`` column.
    kwargs = {}
    if body and body.username:
        kwargs["username"] = body.username
    if body and body.password:
        kwargs["password"] = body.password
    try:
        return reset_service.reset_database(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
