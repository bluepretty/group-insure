"""Server-rendered HTML pages for the admin UI."""
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.auth import require_user
from app.core.database import get_db
from app.core.security import create_token, hash_password, verify_password
from app.models.user import User
from app.services.reports import build_report
from app.view import templates

router = APIRouter(tags=["pages"])


@router.get("/")
def index(request: Request, user: User = Depends(require_user)) -> dict:
    return {"message": f"Welcome, {user.username}"}


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html", {})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/register.html", {})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(require_user),
    db = Depends(get_db),
) -> HTMLResponse:
    report = build_report(db)
    return templates.TemplateResponse(
        request,
        "auth/dashboard.html",
        {"user": user, "report": report},
    )
