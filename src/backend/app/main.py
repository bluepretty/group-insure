"""FastAPI application factory and entrypoint."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import auth, audit, benefits, billing, claims, life_events, members, pages, parties, policies, premiums, products, reports, statements
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


# Domain errors (ValueError raised by service/business logic) should surface as
# a clean 400 rather than leaking as an unhandled 500, so clients get a stable,
# structured error. Genuine bugs (TypeError, KeyError, DB/IntegrityError) are
# intentionally *not* caught here and still reach FastAPI's default 500 handler.
@app.exception_handler(ValueError)
async def _handle_value_error(request, exc: ValueError):
    return JSONResponse(
        status_code=400, content={"detail": str(exc) or "Validation error"}
    )


# Import so models register with the metadata before create_all.
from app import models  # noqa: E402,F401


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
