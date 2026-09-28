"""Party CRUD + helpers. Party is a policyholder (employer/association) or broker."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.lookup import PartyRole
from app.models.party import Party
from app.models.policy import Policy
from app.models.member import Member
from app.services.audit import record_log
from app.services.lookup import validate_kind_code
from app.services.validators import validate_email

# Legacy single-column spellings the party API has always accepted (the
# historical {policyholder, broker}) mapped to the role codes now seeded in the
# party_roles table. This keeps the existing test payloads (which POST
# "policyholder"/"broker") working without touching them: the raw value the
# caller sent is kept for display (stored in party_type), but the role that
# actually references the table is the mapped code.
_ROLE_CODE_ALIASES: dict[str, str] = {
    "policyholder": "policy_holder",
    "broker": "broker",
}


def _normalize_role(raw: str) -> str:
    """Map a legacy party_type spelling to the role code used for validation."""
    return _ROLE_CODE_ALIASES.get(raw, raw)


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
    roles: list[str] | None = None,
) -> Party:
    """Create a party.

    ``party_type`` is the union field: it accepts the legacy role spellings
    (``policyholder``/``broker``, mapped to the role codes) or a new entity-type
    code (``individual``/``corporation``/``trust``); either way it is validated
    against the party_types table when it is an entity type, or the
    party_roles table when it is a role code. ``roles`` carries any *additional*
    role codes the party should hold, so a party can be both a broker and a
    policyholder. The party_type column stores the (possibly mapped) code for
    display/back-compat.
    """
    party = Party(
        name=name,
        email=validate_email(email),
        broker_id=broker_id,
        organization_id=organization_id,
        active=active,
    )
    _apply_roles_and_type(db, party, party_type=party_type, roles=roles)
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
    roles: list[str] | None = None,
) -> Party:
    """Update a party's mutable fields.

    ``name`` / ``party_type`` are required and validated. ``email``, when
    present, must be a valid address; ``active`` soft-deletes the party. Nothing
    is committed here so the caller can bundle the write with an audit log in one
    transaction. ``roles`` replaces the party's role set entirely.
    """
    if name is not None:
        party.name = name
    if party_type is not None:
        _apply_roles_and_type(db, party, party_type=party_type, roles=None)
    if roles is not None:
        _set_roles(db, party, roles)
    if email is not None:
        party.email = validate_email(email) or None
    if active is not None:
        party.active = active
    if organization_id is not None:
        party.organization_id = organization_id
    return party


def _apply_roles_and_type(
    db: Session,
    party: Party,
    *,
    party_type: str,
    roles: list[str] | None,
) -> None:
    """Validate the union-field party_type and wire roles onto the party.

    The raw value is validated against whichever lookup it belongs to (role
    codes against party_roles, entity types against party_types); the raw code
    is stored on ``party.party_type``; and role membership is derived from it
    plus any extra ``roles`` supplied.
    """
    normalized = _normalize_role(party_type)
    try:
        if normalized in _ROLE_CODE_ALIASES or _is_role_code(db, normalized):
            validate_kind_code(db, "party_roles", normalized)
            if normalized != party_type and normalized in _ROLE_CODE_ALIASES:
                party_type = normalized
            party.party_type = normalized
            role_codes = [normalized]
        else:
            # Not a role code -> an entity type.
            validate_kind_code(db, "party_types", party_type)
            party.party_type = party_type
            role_codes = []
    except ValueError:
        raise ValueError(f"Invalid party_type: {party_type!r}")

    all_role_codes = list(role_codes)
    if roles:
        all_role_codes.extend(roles)
    _set_roles(db, party, all_role_codes)


def _set_roles(db: Session, party: Party, role_codes: list[str]) -> None:
    """Replace the party's roles with the given codes, validating each."""
    party.roles = []
    if not role_codes:
        return
    for raw in role_codes:
        normalized = _normalize_role(raw)
        validate_kind_code(db, "party_roles", normalized)
    party.roles = [
        db.get(PartyRole, _normalize_role(code)) for code in role_codes
    ]


def _is_role_code(db: Session, code: str) -> bool:
    return db.scalar(
        select(PartyRole).where(PartyRole.code == code, PartyRole.is_active.is_(True))
    ) is not None


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
