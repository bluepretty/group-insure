"""Models package — import so each model registers with Base.metadata."""
from app.models.audit import AuditLog
from app.models.organization import Organization
from app.models.party import Party
from app.models.policy import Policy
from app.models.member import Member
from app.models.benefit import Benefit
from app.models.member_benefit import MemberBenefit
from app.models.product import Product
from app.models.user import User
from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.claim import Claim
from app.models.life_event import LifeEvent

__all__ = [
    "AuditLog",
    "Member",
    "MemberBenefit",
    "Organization",
    "Party",
    "Policy",
    "Benefit",
    "Product",
    "User",
    "Invoice",
    "Payment",
    "Claim",
    "LifeEvent",
]
