"""FastAPI application factory and entrypoint."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import auth, audit, benefits, billing, claims, life_events, lookup, members, pages, parties, policies, premiums, products, reports, reset, statements, users
from app.core.database import engine, Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Group Insurance Admin Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router, prefix="/api/auth")
app.include_router(parties.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(policies.router)
app.include_router(benefits.router)
app.include_router(premiums.router)
app.include_router(billing.router)
app.include_router(claims.router)
app.include_router(members.router)
app.include_router(audit.router)
app.include_router(life_events.router)
app.include_router(pages.router)
app.include_router(reports.router)
app.include_router(statements.router)
app.include_router(reset.router)
app.include_router(lookup.router)


# Domain errors (ValueError raised by service/business logic) should surface as
# a clean 400 rather than leaking as an unhandled 500, so clients get a stable,
# structured error. Genuine bugs (TypeError, KeyError, DB/IntegrityError) are
# intentionally *not* suppressed: they still raise, return 500, and are logged,
# so we never mask them as a success. We only change the *response body* from
# FastAPI's default HTML page into structured JSON so the htmx banner (which
# parses JSON) can show a readable message instead of raw HTML.
@app.exception_handler(ValueError)
async def _handle_value_error(request, exc: ValueError):
    return JSONResponse(
        status_code=400, content={"detail": str(exc) or "Validation error"}
    )


@app.exception_handler(Exception)
async def _handle_unexpected(request, exc: Exception):
    # Log the traceback (preserves debugging) but return a JSON body so clients
    # don't get FastAPI's default HTML 500 page.
    logging.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Exception": type(exc).__name__},
    )


# Import so models register with the metadata before create_all.
from app import models  # noqa: E402,F401


@app.on_event("startup")
def on_startup() -> None:
    # Ensure the database is reachable before touching it. Free-tier
    # providers (e.g. Neon) scale compute to zero and refuse the first
    # connection after idle; this retries with a backoff instead of
    # crash-looping.
    from app.core.database import connect_with_retry

    connect_with_retry()
    Base.metadata.create_all(bind=engine)
    # Seed the reference/lookup tables so the app is usable against a fresh
    # database (and idempotent on every restart).
    from app.services.lookup import seed_reference_data
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        seed_reference_data(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
