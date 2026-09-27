"""Life-event log (Stage 12): the durable "why/when" trail for census changes.

A ``LifeEvent`` records exactly one mid-term membership change — who did it,
when coverage actually changed, and why. It is pure tracking here; the billing
effect is a separate path in ``services/proration.py``. Every census change
(add/remove) records a ``LifeEvent`` and an audit line.
"""
import datetime as dt

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.life_event import LIFE_EVENT_TYPES, LifeEvent
from app.services.audit import record_log


def record_event(
    db,
    *,
    policy_id: int,
    member_id: int | None = None,
    event_type: str,
    effective_date: dt.date,
    actor_id: int | None = None,
    details: str | None = None,
) -> LifeEvent:
    """Record a mid-term membership change.

    Inserts a ``LifeEvent`` (the durable "why/when" trail) and mirrors it into
    the shared audit log. Raises ``ValueError`` for an unknown ``event_type``.
    Never raises on the audit line itself — :func:`record_log` never raises.
    """
    if event_type not in LIFE_EVENT_TYPES:
        raise ValueError(
            f"Unknown event_type {event_type!r}; expected one of "
            f"{', '.join(LIFE_EVENT_TYPES)}"
        )
    event = LifeEvent(
        policy_id=policy_id,
        member_id=member_id,
        event_type=event_type,
        effective_date=effective_date,
        actor_id=actor_id,
        details=details,
    )
    db.add(event)
    db.commit()
    record_log(
        db,
        action="life_event",
        actor_id=actor_id,
        entity="LifeEvent",
        entity_id=event.id,
        details=(
            f"policy_id={policy_id} member_id={member_id} "
            f"event_type={event_type} effective_date={effective_date.isoformat()}"
        ),
    )
    return event


def list_events(
    db,
    *,
    policy_id: int | None = None,
    event_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[LifeEvent]:
    """List life events, optionally filtered by policy and/or event type."""
    stmt = select(LifeEvent)
    if policy_id is not None:
        stmt = stmt.where(LifeEvent.policy_id == policy_id)
    if event_type is not None:
        stmt = stmt.where(LifeEvent.event_type == event_type)
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset is not None:
        stmt = stmt.offset(offset)
    return db.scalars(stmt.order_by(LifeEvent.created_at.desc())).all()


def list_events_for_policy(policy_id: int, actor_id: int | None = None) -> list:
    """Thin list view over the events table for the member-list partial.

    Returns ``LifeEvent`` rows for the policy, newest first. Kept separate from
    ``list_events`` so the API/View layer has a single, obvious entry point and
    the DB access pattern is explicit.
    """
    db = SessionLocal()
    try:
        return list_events(db, policy_id=policy_id)
    finally:
        db.close()
