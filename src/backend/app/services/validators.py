"""Shared input validation helpers.

Email addresses are a first-class, *optional* field on every external record
(policyholder/broker Party, Organization, User). A present value must look like a
valid address, but absence is always allowed. ``validate_email`` is the single
source of truth so no record type drifts on what "valid" means.
"""
import re

# Minimal, correct-for-email: local@tld with a dot in the TLD. Deliberately not
# a full RFC 5322 parse — we only need to reject the obvious mistakes.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(value: str | None) -> str | None:
    """Lowercase/strip ``value`` or return ``None`` if it is empty.

    Raises ``ValueError`` for a non-empty value that is not a syntactically valid
    email address. ``None`` and empty/whitespace strings are both accepted and
    normalised to ``None``.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        raise ValueError(f"Invalid email address: {value!r}")
    return value.lower()
