"""Audit logging helper.

Wrrites to the ``audit_log`` table using the shared ``AuditLog`` model.
"""
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_log(
    db: Session,
    *,
    action: str,
    actor_id: int | None = None,
    entity: str | None = None,
    entity_id: int | None = None,
    details: str | None = None,
) -> None:
    """Append one audit record. Never raises — auditing must not break the
    caller's main work."""
    try:
        db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                entity=entity,
                entity_id=entity_id,
                details=details,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
