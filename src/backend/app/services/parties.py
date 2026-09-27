"""Party CRUD + helpers. Party is a policyholder (employer/association) or broker."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.party import Party
from app.models.policy import Policy
from app.models.member import Member
from app.services.audit import record_log
from app.services.validators import validate_email


def list_parties(db: Session, *, active_only: bool = True, org_id: int | None = None) -> list[Party]:
    stmt = select(Party)
    if active_only:
        stmt = stmt.where(Party.active.is_(True))
    if org_id is not None:
        stmt = stmt.where(Party.organization_id == org_id)
    stmt = stmt.order_by(Party.created_at.desc())
    return db.scalars(stmt).all()


def get_party(db: Session, party_id: int) -> Party | None:
    return db.get(Party, party_id)


def count_active(db: Session) -> int:
    return db.scalar(select(Party).where(Party.active.is_(True)))


def add_party(
    db: Session,
    *,
    name: str,
    party_type: str,
    email: str | None = None,
    broker_id: int | None = None,
    organization_id: int | None = None,
    active: bool = True,
) -> Party:
    party = Party(
        name=name,
        party_type=party_type,
        email=validate_email(email),
        broker_id=broker_id,
        organization_id=organization_id,
        active=active,
    )
    db.add(party)
    db.commit()
    record_log(db, action="party_create", entity="Party", entity_id=party.id)
    return party


def update_party(
    db: Session,
    party: Party,
    *,
    name: str | None = None,
    party_type: str | None = None,
    email: str | None = None,
    active: bool | None = None,
    organization_id: int | None = None,
) -> Party:
    """Update a party's mutable fields.

    ``name`` / ``party_type`` are required and validated. ``email``, when
    present, must be a valid address; ``active`` soft-deletes the party. Nothing
    is committed here so the caller can bundle the write with an audit log in one
    transaction.
    """
    if name is not None:
        party.name = name
    if party_type is not None:
        party.party_type = party_type
    if email is not None:
        party.email = validate_email(email) or None
    if active is not None:
        party.active = active
    if organization_id is not None:
        party.organization_id = organization_id
    return party


def party_usage(db: Session, party_id: int) -> dict:
    """Counts of rows that would be orphaned if ``party_id`` were removed.

    A policy's ``party_id`` and a member's ``party_id`` are nullable (existing
    seeds may be NULL), but an active policy/member pointing at this party means
    deleting it would break a join. ``{ok: True, ...}`` means it is safe to
    deactivate.
    """
    policies = db.scalar(
        select(func.count()).select_from(Policy).where(Policy.party_id == party_id)
    )
    members = db.scalar(
        select(func.count()).select_from(Member).where(Member.party_id == party_id)
    )
    return {
        "ok": policies == 0 and members == 0,
        "policies": policies,
        "members": members,
    }
