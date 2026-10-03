"""SQLAlchemy engine and session helpers."""
import logging
import threading
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def get_db():
    """Yield a database session and always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def connect_with_retry(max_retries: int = 6, delay: float = 5.0) -> None:
    """Connect once, retrying on transient failures.

    Free-tier providers (e.g. Neon) scale compute to zero and refuse the
    first connection after idle. This waits a few seconds between attempts
    so the compute can wake up instead of the app crash-looping.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "DB connect attempt %s/%s failed: %s: %s",
                attempt,
                max_retries,
                type(exc).__name__,
                str(exc)[:120],
            )
            if attempt < max_retries:
                time.sleep(delay)
    if last_error is not None:
        raise last_error


def create_schema() -> None:
    """Create the schema and (re)seed reference data.

    Best-effort: the database is not required for the health check to
    pass, so this must never block or crash startup. It retries with a
    long backoff so a cold, scaled-to-zero compute can still be reached.
    Returns without raising if the database is unreachable.
    """
    global _SCHEMA_READY
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
    try:
        connect_with_retry(max_retries=36, delay=10)  # up to ~6 minutes
        Base.metadata.create_all(bind=engine)
        with _SCHEMA_LOCK:
            if _SCHEMA_READY:
                return
            from app.services.lookup import seed_reference_data

            db = SessionLocal()
            try:
                seed_reference_data(db)
            finally:
                db.close()
            _SCHEMA_READY = True
            logger.info("Database schema initialized and seeded.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Schema init deferred (DB unavailable): %s", str(exc)[:160])


def init_database() -> None:
    """Bootstrap the database without blocking the startup probe.

    Runs schema creation in the background so a free-tier compute that is
    still cold does not take the whole service down. The service becomes
    ready immediately; the schema is created as soon as the database is
    reachable.
    """
    if not _SCHEMA_READY:
        threading.Thread(target=create_schema, daemon=True).start()
