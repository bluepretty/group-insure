"""User model for professional accounts (underwriter / broker)."""
import datetime as dt

import bcrypt
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def hash_password(password: str) -> str:
    # bcrypt rejects anything above 72 bytes; truncate to match bcrypt's real
    # behaviour (it silently ignores trailing bytes) so long passwords register
    # and verify consistently instead of raising a 500 on registration.
    password = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    # Match ``hash_password``: bcrypt rejects inputs above 72 bytes, so a long
    # password must be truncated to the same bytes that were actually hashed or
    # ``checkpw`` raises ``ValueError`` and login fails for a perfectly valid
    # password.
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72], hashed.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(255))
    roles: Mapped[str] = mapped_column(String(255))  # semicolon-separated
    # Email is a first-class, optional field: any present value is validated
    # (validators.validate_email), but absence is always allowed. Nullable so
    # existing records and the smoke DB are unaffected.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
