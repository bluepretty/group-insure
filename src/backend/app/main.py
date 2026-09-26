"""FastAPI application factory and entrypoint."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import auth, audit, benefits, billing, claims, members, pages, parties, policies, premiums, products, reports, statements
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

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
app.include_router(pages.router)
app.include_router(reports.router)
app.include_router(statements.router)

# Import so models register with the metadata before create_all.
from app import models  # noqa: E402,F401


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
