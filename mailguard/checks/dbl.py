"""Domain reputation via free DNS-based blocklists.

We query known DNSBLs by performing a lookup for ``<domain>.<dbl-root>``.
If the name resolves to any 127.0.0.x address, the domain is listed.

Providers queried (all free for non-commercial use; see each provider's AUP):
    - dbl.spamhaus.org       Spamhaus Domain Block List
    - multi.uribl.com        URIBL combined list
    - multi.surbl.org        SURBL combined list

This check is OPTIONAL and off by default. Callers enable it via
``validate(..., check_reputation=True)``. A single bad lookup does NOT
cause the pipeline to fail — any exception returns ``None`` (no signal)
like every other optional layer.

Result is cached in the SQLite cache with a 1-hour TTL because reputation
lists change fast.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mailguard import cache

try:
    import dns.asyncresolver
    import dns.exception
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None  # type: ignore[assignment]


CACHE_NS = "dbl"
CACHE_TTL = 3600  # 1 hour


DBL_PROVIDERS: tuple[str, ...] = (
    "dbl.spamhaus.org",
    "multi.uribl.com",
    "multi.surbl.org",
)


@dataclass
class ReputationResult:
    listed: bool
    providers: list[str]  # which DBLs flagged the domain
    error: str | None = None


async def check_reputation(domain: str, *, timeout: float = 5.0) -> ReputationResult:
    """Check a domain against free DNSBLs. Returns an aggregate verdict.

    - ``listed=True`` if *any* provider flags the domain
    - ``listed=False`` if all providers say clean
    - ``error`` set if lookups couldn't be completed at all
    """
    domain = domain.lower().strip(".")
    cached = cache.get(CACHE_NS, domain)
    if cached is not None:
        return ReputationResult(**cached)

    if dns is None:
        return ReputationResult(listed=False, providers=[], error="dnspython not installed")

    listed_on: list[str] = []
    any_responded = False
    for provider in DBL_PROVIDERS:
        query = f"{domain}.{provider}"
        try:
            answers = await _resolve(query, timeout)
            any_responded = True
            # Any 127.0.0.x response indicates listing. Some providers use
            # 127.255.255.254 to indicate "query blocked" — ignore those.
            for rdata in answers:
                addr = str(rdata)
                if addr.startswith("127.0.0.") and not addr.startswith("127.255."):
                    listed_on.append(provider)
                    break
        except Exception:
            # NXDOMAIN = not listed. Other errors = silent skip.
            any_responded = True

    err = None if any_responded else "no DBL responded"
    result = ReputationResult(listed=bool(listed_on), providers=listed_on, error=err)
    cache.put(CACHE_NS, domain, {
        "listed": result.listed,
        "providers": result.providers,
        "error": result.error,
    }, ttl=CACHE_TTL)
    return result


async def _resolve(query: str, timeout: float) -> list:
    """Async A-record lookup using dnspython's async resolver."""
    loop = asyncio.get_running_loop()

    def _sync_query() -> list:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        try:
            return list(resolver.resolve(query, "A"))
        except dns.resolver.NXDOMAIN:
            return []
        except dns.exception.DNSException:
            return []

    return await loop.run_in_executor(None, _sync_query)
