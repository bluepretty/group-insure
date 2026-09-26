"""Authentication endpoints: register, login, logout.

Professional accounts only (underwriter / broker). Login issues a JWT;
endpoints are served via HTML templates for the server-rendered admin UI.
"""
from typing import Any

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_token, decode_token, verify_password
from app.models.user import User, hash_password
from app.services.audit import record_log
from app.services.validators import validate_email

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
        "view_premiums",
        "manage_premiums",
        "view_billing",
        "manage_billing",
        "view_claims",
    },
    "broker": {
        "view_dashboard",
        "manage_parties",
        "view_policies",
        "view_products",
        "view_members",
        "view_benefits",
        "view_premiums",
        "view_billing",
        "view_claims",
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
    try:
        email = validate_email(payload.email)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    user = User(
        username=payload.username,
        password=hash_password(payload.password),
        roles=payload.roles,
        email=email,
        active=True,
    )
    db.add(user)
    db.commit()
    record_log(db, action="register", actor_id=user.id, entity="User", entity_id=user.id)
    return {"id": user.id, "username": user.username}


@router.post("/login", response_model=dict)
async def login(
    request: Request,
    username: str | None = Form(None),
    password: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    """Authenticate and issue a JWT.

    Accepts both `application/x-www-form-urlencoded` (the server-rendered
    login.html form, the normal browser path) and `application/json` (API/HTMX
    clients that POST a JSON body). FastAPI can't merge a Form field and a
    JSON body in one signature, so we pull the raw JSON body ourselves when no
    form fields are present.
    """
    # HTML form posts urlencoded data — take those first.
    if username is None or password is None:
        # Fall back to a JSON body (API/HTMX clients).
        try:
            data = await request.json()
            username = data.get("username")
            password = data.get("password")
        except Exception:
            username = password = None
    if not username or not password:
        raise HTTPException(
            status_code=400, detail="username and password are required"
        )
    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.roles)
    resp = JSONResponse(content={"access_token": token, "token_type": "bearer"})
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    # htmx-native redirect: the server-rendered login form uses an
    # ``hx-post`` form whose ``hx-on::after-request`` was unreliable because the
    # JSON body isn't a swap-valid target. htmx's ``HX-Redirect`` header, however,
    # makes the client navigate itself regardless of swap validity — no JS needed.
    resp.headers["HX-Redirect"] = "/dashboard"
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
