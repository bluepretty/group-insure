"""Party CRUD + helpers. Party is a policyholder (employer/association) or broker."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.party import Party
from app.services.audit import record_log


def list_parties(db: Session, *, org_id: int | None = None) -> list[Party]:
    stmt = select(Party)
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
    broker_id: int | None = None,
    organization_id: int | None = None,
    active: bool = True,
) -> Party:
    party = Party(
        name=name,
        party_type=party_type,
        broker_id=broker_id,
        organization_id=organization_id,
        active=active,
    )
    db.add(party)
    db.commit()
    record_log(db, action="party_create", entity="Party", entity_id=party.id)
    return party
