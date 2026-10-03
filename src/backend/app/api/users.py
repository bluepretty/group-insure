"""User management endpoints (CRUD) and HTMX partials.

Admin-only. ``manage_users`` (underwriter) is the sole permission; a broker
cannot list, edit, or delete any account.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.auth import _has_permission, require_role, require_user
from app.api.auth import User
from app.core.database import get_db
from app.services.audit import record_log
from app.services.users import (
    get_user,
    list_users,
    set_password,
    update_user,
    user_usage,
)
from app.view import templates

router = APIRouter(prefix="/api/users", tags=["users"])



@router.get("")
def list_users_endpoint(
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_users")),
) -> list[dict]:
    """API: list users (JSON)."""
    return [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "roles": user.roles,
            "active": user.active,
        }
        for user in list_users(db)
    ]


@router.get("/list")
def user_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/user_list.html",
        {"users": list_users(db), "can_reset": _has_permission(user, "manage_users")},
    )


@router.get("/{user_id}", response_model=None)
def get_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
) -> dict | JSONResponse:
    """API: one user, for pre-filling the edit modal."""
    target = get_user(db, user_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    return {
        "id": target.id,
        "username": target.username,
        "email": target.email,
        "roles": target.roles,
        "active": target.active,
    }


@router.put("/{user_id}")
def edit_user(
    user_id: int,
    roles: str = Form(...),
    email: str | None = Form(None),
    active: bool = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_users")),
) -> JSONResponse:
    """Update a user's roles / email / active flag."""
    target = get_user(db, user_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    try:
        update_user(db, target, roles=roles, email=email, active=active)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    record_log(db, action="user_edited", actor_id=user.id, entity="User", entity_id=target.id)
    return JSONResponse(content={"id": target.id, "username": target.username})


@router.post("/{user_id}/set-password")
def set_user_password(
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_users")),
) -> JSONResponse:
    """Set a new password for a user. Returns a plain-text password only on success."""
    target = get_user(db, user_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    if len(new_password) < 8:
        return JSONResponse(status_code=400, content={"detail": "Password must be at least 8 characters long"})
    set_password(db, target, new_password)
    record_log(db, action="user_password_set", actor_id=user.id, entity="User", entity_id=target.id)
    return JSONResponse(content={"id": target.id})


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("manage_users")),
) -> JSONResponse:
    """Delete a user, unless they are in use.

    400 if the caller tries to delete their own account; 409 with counts if
    they own policies/claims. 200 ({"ok": true}) otherwise.
    """
    if user_id == user.id:
        return JSONResponse(status_code=400, content={"detail": "Cannot delete your own account"})
    target = get_user(db, user_id)
    if not target:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    usage = user_usage(db, user_id)
    if not usage["ok"]:
        reasons = []
        if usage["policies"]:
            reasons.append(f"{usage['policies']} policies underwritten")
        if usage["life_events"]:
            reasons.append(f"{usage['life_events']} life events")
        return JSONResponse(
            status_code=409,
            content={"detail": "Cannot delete user: still in use by " + ", ".join(reasons)},
        )
    db.delete(target)
    db.commit()
    record_log(db, action="user_deleted", actor_id=user.id, entity="User", entity_id=user_id)
    return JSONResponse(content={"ok": True})
