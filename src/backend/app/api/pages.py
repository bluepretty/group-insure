"""Server-rendered HTML pages for the admin UI."""
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.auth import require_admin, require_user, _has_permission
from app.core.database import get_db
from app.core.security import create_token, hash_password, verify_password
from app.models.user import User
from app.services.lookup import list_lookup, seed_reference_data
from app.services.reports import build_report
from app.view import templates

router = APIRouter(tags=["pages"])


@router.get("/")
def index(request: Request, user: User = Depends(require_user)) -> dict:
    return {"message": f"Welcome, {user.username}"}


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html", {})


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
        {"user": user, "report": report, "manage_users": _has_permission(user, "manage_users")},
    )


@router.get("/lookup-management/{kind}", response_class=HTMLResponse)
def lookup_management_page(
    kind: str,
    request: Request,
    db = Depends(get_db),
    _: User = Depends(require_admin),
) -> HTMLResponse:
    """Server-rendered reference-data maintenance (super-admin only).

    ``kind`` is one of ``party_types`` / ``party_roles`` / ``policy_statuses``.
    Admins add a row with the inline form (POST to ``/api/lookup``), edit or
    reactivate a row from the modal (PUT to ``/api/lookup/{kind}/{code}``), and
    soft-delete a row that nothing references (DELETE to the same path). The
    backend guards every write with the ``manage_references`` permission, so a
    non-admin who reaches this page gets a 403 rather than an edit box.
    """
    seed_reference_data(db)
    return templates.TemplateResponse(
        request,
        "partials/lookup_management_list.html",
        {"kind": kind, "values": list_lookup(db, kind)},
    )