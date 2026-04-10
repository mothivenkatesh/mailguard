"""Catch-all domain detection.

A catch-all domain accepts mail for any local part at its domain. If a
domain is catch-all, an SMTP RCPT probe cannot distinguish real mailboxes
from fake ones — so we MUST down-weight SMTP results for these domains.

Detection probes a deliberately-random local part. If the MX says "yes",
the domain is catch-all.
"""
from __future__ import annotations

import secrets

from mailguard.checks.smtp_check import smtp_probe


async def detect_catchall(domain: str, mx_host: str, *, timeout: float = 10.0) -> bool | None:
    """Return True if the domain accepts mail for a random local part.

    Returns None if the probe could not complete (port blocked, timeout).
    """
    random_local = f"mailguard-probe-{secrets.token_hex(6)}"
    fake = f"{random_local}@{domain}"
    result = await smtp_probe(fake, mx_host, timeout=timeout)
    return result  # True=catch-all, False=normal, None=unknown
