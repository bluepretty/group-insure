"""Database reset: wipe all business data and leave exactly one super-admin.

This is a deliberately heavy hammer and it is intentionally scoped narrowly.
The finite lookup values the domain relies on (party type, policy status, etc.)
now live in database tables — see ``app.services.lookup`` — and are the kind of
reference data the reset is meant to *preserve*, so the lookup tables are not
erased. They are re-seeded after the wipe so a reset leaves a clean, populated
baseline (and idempotently, if they were already present). The ``organizations``
table is also preserved (the tenant record), and the ``users`` table is reset to
a single super-admin rather than emptied. Test-stage only: the audit log is
wiped too.

Every business table is emptied. ``users`` is then collapsed to a single
super-admin account: ``admin`` / the value of ``DEFAULT_SUPER_ADMIN_PASSWORD``
(defaults to ``admin``).
"""
from app.core.database import SessionLocal
from app.models.audit import AuditLog
from app.models.benefit import Benefit
from app.models.claim import Claim
from app.models.invoice import Invoice
from app.models.life_event import LifeEvent
from app.models.lookup import PartyRole, PartyType, PolicyStatus
from app.models.member import Member
from app.models.member_benefit import MemberBenefit
from app.models.party import Party
from app.models.payment import Payment
from app.models.policy import Policy
from app.models.product import Product
from app.models.user import User, hash_password
from app.services.lookup import seed_reference_data

# Tables emptied on reset, from most-referenced to least (deleting children
# before parents keeps FK ordering irrelevant). Test-stage only: the audit log
# is wiped too (there is no audit trail to preserve in a reset DB).
ERASE_ORDER: tuple[type, ...] = (
    MemberBenefit,
    Payment,
    LifeEvent,
    Claim,
    Invoice,
    Policy,
    Member,
    Party,
    Product,
    Benefit,
    AuditLog,
)

# The sole account left behind. ``users`` itself is preserved as a table but is
# emptied of every row except this one.
DEFAULT_SUPER_ADMIN_USERNAME = "admin"
DEFAULT_SUPER_ADMIN_PASSWORD = "admin"


def reset_database(
    *,
    username: str = DEFAULT_SUPER_ADMIN_USERNAME,
    password: str | None = None,
) -> dict:
    """Delete every row in the business tables and reset users to one super-admin.

    ``password`` defaults to ``DEFAULT_SUPER_ADMIN_PASSWORD``; an empty
    password is rejected here so the reset can never leave the super-admin
    without a credential. Unlike registration, the short default (``admin``)
    is permitted — this is an admin bootstrap, not self-service signup.
    """
    password = (password or DEFAULT_SUPER_ADMIN_PASSWORD)
    if not password:
        raise ValueError("Password must not be empty")

    db = SessionLocal()
    try:
        # Wipe every erased table. Deleting children before parents avoids FK
        # complaints on back-referencing tables; the audit log is wiped too
        # because this reset exists in the test stage only.
        for model in ERASE_ORDER:
            db.query(model).delete()

        # ``users`` is reset, not emptied: drop every row so exactly one super
        # admin remains, then create it. commit() is required here — a bare
        # flush() would leave the whole wipe uncommitted and rolled back on
        # session close.
        db.query(User).delete()
        user = User(
            username=username,
            password=hash_password(password),
            roles="admin",
            active=True,
        )
        db.add(user)
        db.commit()
        return {
            "ok": True,
            "message": "Database reset. All business data and audit log erased; one super-admin remains.",
            "admin_username": username,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
