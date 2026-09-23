"""Authentication endpoints: register, login, logout.

Professional accounts only (underwriter / broker). Login issues a JWT;
endpoints are served via HTML templates for the server-rendered admin UI.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_token, decode_token, verify_password
from app.models.user import User, hash_password
from app.services.audit import record_log

router = APIRouter(tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


class LoginModel(BaseModel):
    username: str
    password: str


class RegisterModel(BaseModel):
    username: str
    password: str
    email: EmailStr
    roles: str = "broker"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    # An explicit Authorization header takes precedence; otherwise fall back to
    # the session cookie set on login. A bare cookie otherwise shadows an
    # incoming Bearer header and would attribute the call to whoever last
    # logged in, so the header wins.
    authorization = request.headers.get("Authorization", "")
    token = None
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = payload["sub"]
    except Exception:
        return None
    return db.get(User, int(user_id))


def require_user(user: User = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# Role -> permissions map. Adding a permission or a new role here is all that's
# required; call sites only reference permissions via require_role().
_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "underwriter": {
        "view_dashboard",
        "manage_parties",
        "view_products",
        "manage_products",
        "view_policies",
        "manage_policies",
        "manage_claims",
        "view_members",
        "manage_members",
        "view_benefits",
        "manage_benefits",
    },
    "broker": {
        "view_dashboard",
        "manage_parties",
        "view_policies",
        "view_products",
        "view_members",
        "view_benefits",
    },
}


def _has_permission(user: User, permission: str) -> bool:
    roles = {r.strip() for r in user.roles.split(";") if r.strip()}
    return any(permission in _ROLE_PERMISSIONS.get(role, set()) for role in roles)


def require_role(permission: str):
    """FastAPI dependency that only succeeds for users holding ``permission``."""

    def _checker(user: User = Depends(require_user)) -> User:
        if not _has_permission(user, permission):
            raise HTTPException(
                status_code=403, detail=f"Missing permission: {permission}"
            )
        return user

    return _checker


@router.post("/register", response_model=dict)
def register(payload: RegisterModel, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=payload.username,
        password=hash_password(payload.password),
        roles=payload.roles,
        active=True,
    )
    db.add(user)
    db.commit()
    record_log(db, action="register", actor_id=user.id, entity="User", entity_id=user.id)
    return {"id": user.id, "username": user.username}


@router.post("/login", response_model=dict)
def login(payload: LoginModel, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.roles)
    resp = JSONResponse(content={"access_token": token, "token_type": "bearer"})
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    record_log(db, action="login", actor_id=user.id, entity="User", entity_id=user.id)
    return resp


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/me")
def me(user: User = Depends(require_user)) -> dict:
    return {"id": user.id, "username": user.username, "roles": user.roles}
