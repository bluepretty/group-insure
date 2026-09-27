"""User management helpers: list, fetch, edit, and the delete guard.

Users are admin-only professional accounts (underwriter / broker). The functions
here back the ``/api/users`` CRUD routes; the delete guard lives here (not in the
route) so it is unit-testable and reusable by any other caller.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User, hash_password
from app.models.policy import Policy
from app.models.life_event import LifeEvent
from app.services.validators import validate_email


def list_users(db: Session) -> list[User]:
    """All users, ordered by id."""
    return db.scalars(select(User).order_by(User.id)).all()


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def update_user(
    db: Session,
    user: User,
    *,
    roles: str | None = None,
    email: str | None = None,
    active: bool | None = None,
) -> User:
    """Update an existing user's mutable fields.

    ``roles`` must be an approved professional role (server-owned allow-list).
    ``email``, when present, must be a valid address. ``active`` toggles the
    lock-out flag. Returns the updated user; nothing is committed here so the
    caller can bundle the write with an audit log in one transaction.
    """
    if roles is not None:
        roles = roles.strip()
        if roles not in ("underwriter", "broker"):
            raise ValueError(f"Invalid role {roles!r}. Allowed: underwriter, broker")
        user.roles = roles
    if email is not None:
        try:
            validated = validate_email(email)
        except ValueError as exc:
            raise ValueError(str(exc))
        user.email = validated
    if active is not None:
        user.active = active
    return user


def set_password(db: Session, user: User, raw_password: str) -> User:
    """Set a new password for ``user``. Returns the user (unchanged transaction)."""
    user.password = hash_password(raw_password)
    return user


def user_usage(db: Session, user_id: int) -> dict:
    """Return counts of rows that would be orphaned if ``user_id`` were deleted.

    Two FK chains point at ``users`` with NOT NULL semantics that matter at delete:
    a policy's ``underwriter_id`` and a life event's ``actor_id``. Audit-log
    ``actor_id`` rows are historical and nullable, so they do not block a delete.
    ``{ok: True, ...}`` means the user is safe to remove.
    """
    policies = db.scalar(
        select(func.count()).select_from(Policy).where(Policy.underwriter_id == user_id)
    )
    life_events = db.scalar(
        select(func.count()).select_from(LifeEvent).where(LifeEvent.actor_id == user_id)
    )
    return {
        "ok": policies == 0 and life_events == 0,
        "policies": policies,
        "life_events": life_events,
    }


def register_user(db: Session, *, username, password, email=None, roles="underwriter", active=True) -> User:
    """Create a user directly (used by the registration flow and tests)."""
    try:
        validated_email = validate_email(email) if email else None
    except ValueError as exc:
        raise ValueError(str(exc))
    user = User(
        username=username,
        password=hash_password(password),
        roles=roles,
        email=validated_email,
        active=active,
    )
    db.add(user)
    db.commit()
    return user
