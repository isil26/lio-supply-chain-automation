"""Recipient allowlist for real (non-demo) supplier email.

Real mail may only go to the case suppliers. By default that is any address
under the hackathon supplier domain. Override with CHASER_ALLOWED_DOMAINS
(comma separated) and/or CHASER_ALLOWED_RECIPIENTS (exact addresses).
"""
import os
from email.utils import parseaddr

DEFAULT_DOMAINS = "suppliers.juliansibbing.de"


def _split(value):
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def check_recipient(address):
    """Raise PermissionError unless the address is an allowed supplier recipient."""
    email = parseaddr(address or "")[1].lower()
    if "@" not in email:
        raise PermissionError(f"refusing real send: invalid recipient {address!r}")
    domains = _split(os.getenv("CHASER_ALLOWED_DOMAINS", DEFAULT_DOMAINS))
    exact = _split(os.getenv("CHASER_ALLOWED_RECIPIENTS"))
    if email in exact or email.rsplit("@", 1)[1] in domains:
        return email
    raise PermissionError(f"refusing real send: {email} is not on the supplier allowlist")
