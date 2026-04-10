"""Catch-all domain detection via multi-probe consensus.

A catch-all domain accepts mail for any local part at its domain. If a
domain is catch-all, an SMTP RCPT probe cannot distinguish real mailboxes
from fake ones — so we MUST down-weight SMTP results for these domains.

v0.3.0 upgrade: probe ``N`` times with different random local parts.
 - Unanimous accept → domain is catch-all (True)
 - Unanimous reject → domain is normal (False)
 - Any disagreement / timeouts → unknown (None)

The unanimity rule prevents one-off rate-limit / greylisting hits from
being misinterpreted as catch-all. Result is cached per domain for 7 days.
"""
from __future__ import annotations

import asyncio
import secrets

from mailguard import cache
from mailguard.checks.smtp_check import smtp_probe

CACHE_NS = "catchall"
CACHE_TTL = 604_800  # 7 days
DEFAULT_PROBE_COUNT = 3


async def detect_catchall(
    domain: str,
    mx_host: str,
    *,
    timeout: float = 10.0,
    probe_count: int = DEFAULT_PROBE_COUNT,
) -> bool | None:
    """Return True if the domain is catch-all, False if normal, None if unknown.

    Runs ``probe_count`` parallel probes against randomly-generated local
    parts and requires unanimity before returning a decisive verdict.
    """
    cached = cache.get(CACHE_NS, domain)
    if cached is not None:
        return cached.get("verdict") if isinstance(cached, dict) else cached

    # Probe ``probe_count`` times with distinct random local parts.
    probe_emails = [
        f"mailguard-probe-{secrets.token_hex(8)}@{domain}" for _ in range(probe_count)
    ]
    tasks = [smtp_probe(e, mx_host, timeout=timeout) for e in probe_emails]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        return None

    # Collect clean results, drop exceptions
    clean = [r for r in results if isinstance(r, (bool, type(None)))]
    trues = sum(1 for r in clean if r is True)
    falses = sum(1 for r in clean if r is False)
    nones = sum(1 for r in clean if r is None)

    # Unanimity rules
    if trues == probe_count:
        verdict: bool | None = True
    elif falses == probe_count:
        verdict = False
    elif nones == probe_count:
        verdict = None
    elif trues > 0 and falses == 0:
        # Some accepts, no rejects — probable catch-all with one flake
        verdict = True
    elif falses > 0 and trues == 0:
        # Some rejects, no accepts — probable normal domain
        verdict = False
    else:
        # Mixed accept+reject = something weird; caller should not trust SMTP
        verdict = None

    cache.put(CACHE_NS, domain, {"verdict": verdict}, ttl=CACHE_TTL)
    return verdict
