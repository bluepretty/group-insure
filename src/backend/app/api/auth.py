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
    # Prefer the session cookie set on login; also accept a Bearer token from
    # the Authorization header for API clients.
    token = request.cookies.get("access_token")
    authorization = request.headers.get("Authorization", "")
    if not token and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
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
    return {"id": user.id, "username": user.username}


@router.post("/login", response_model=dict)
def login(payload: LoginModel, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.roles)
    resp = JSONResponse(content={"access_token": token, "token_type": "bearer"})
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/me")
def me(user: User = Depends(require_user)) -> dict:
    return {"id": user.id, "username": user.username, "roles": user.roles}
