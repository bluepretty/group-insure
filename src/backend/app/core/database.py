"""SQLAlchemy engine and session helpers."""
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


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
            print(
                f"DB connect attempt {attempt}/{max_retries} failed: "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )
            if attempt < max_retries:
                time.sleep(delay)
    if last_error is not None:
        raise last_error
