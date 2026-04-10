"""Async DNS / MX resolution with persistent cache and graceful fallback.

Resolver selection is adaptive:
    1. Try ``aiodns`` (async, fast) if installed.
    2. If aiodns fails at runtime (on Windows it frequently can't
       auto-discover DNS servers and returns ARES_ECONNREFUSED on every
       query), transparently fall back to synchronous ``dnspython`` in a
       thread pool. The fall-back is sticky for the session so we don't
       retry a broken resolver on every call.

This is the fix for a v0.2.0 bug where Windows users saw 100% "no MX
records" on any real list because aiodns silently returned nothing.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from mailguard import cache

try:
    import aiodns
except ImportError:  # pragma: no cover
    aiodns = None  # type: ignore[assignment]

try:
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None  # type: ignore[assignment]


CACHE_NS = "mx"
CACHE_TTL = 86_400  # 1 day

# Sticky flag: once aiodns fails at the "can't contact DNS servers" level,
# we stop using it for the rest of the session and rely on dnspython.
_aiodns_broken = False


@dataclass
class MxResult:
    ok: bool
    host: str = ""
    priority: int = 0
    error: str | None = None


# Process-local dict on top of the persistent cache so repeated lookups
# within a single bulk run don't hit SQLite on every call.
_mem: dict[str, MxResult] = {}


async def resolve_mx(domain: str, *, timeout: float = 10.0) -> MxResult:
    """Resolve MX records for a domain, falling back to A/AAAA.

    Two-tier cache:
        1. Process-local dict (free)
        2. SQLite at ~/.mailguard/cache.db (1-day TTL)
    """
    domain = domain.lower().strip(".")
    if domain in _mem:
        return _mem[domain]

    cached = cache.get(CACHE_NS, domain)
    if cached is not None:
        result = MxResult(**cached)
        _mem[domain] = result
        return result

    result = await _resolve(domain, timeout)
    _mem[domain] = result
    if result.ok:
        cache.put(CACHE_NS, domain, asdict(result), ttl=CACHE_TTL)
    else:
        cache.put(CACHE_NS, domain, asdict(result), ttl=3600)  # shorter negative TTL
    return result


async def _resolve(domain: str, timeout: float) -> MxResult:
    global _aiodns_broken
    if aiodns is not None and not _aiodns_broken:
        result = await _resolve_async(domain, timeout)
        if result.ok or not _looks_like_resolver_failure(result.error):
            return result
        # aiodns can't reach DNS servers — mark broken, fall through to sync
        _aiodns_broken = True
    return await _resolve_sync_in_thread(domain, timeout)


def _looks_like_resolver_failure(err: str | None) -> bool:
    """Heuristic: distinguish 'no such domain' from 'resolver itself broken'."""
    if not err:
        return False
    markers = (
        "could not contact dns servers",
        "dns server",
        "ares_econnrefused",
        "ares_etimeout",
        "ares_eserver",
    )
    low = err.lower()
    return any(m in low for m in markers)


async def _resolve_async(domain: str, timeout: float) -> MxResult:
    resolver = aiodns.DNSResolver(timeout=timeout)
    try:
        records = await asyncio.wait_for(resolver.query(domain, "MX"), timeout=timeout)
        if records:
            best = min(records, key=lambda r: r.priority)
            return MxResult(ok=True, host=best.host.rstrip("."), priority=best.priority)
    except Exception as e:
        # If this is a resolver-level failure, propagate so the caller can
        # switch to sync. Otherwise continue to A-record fallback.
        if _looks_like_resolver_failure(str(e)):
            return MxResult(ok=False, error=f"no MX/A: {e}")
    try:
        await asyncio.wait_for(resolver.query(domain, "A"), timeout=timeout)
        return MxResult(ok=True, host=domain, priority=0)
    except Exception as e:
        return MxResult(ok=False, error=f"no MX/A: {e}")


async def _resolve_sync_in_thread(domain: str, timeout: float) -> MxResult:
    """Run dnspython in a thread so we don't block the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _resolve_sync, domain, timeout)


def _resolve_sync(domain: str, timeout: float) -> MxResult:
    if dns is None:
        return MxResult(ok=False, error="dnspython not installed")
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        answers = resolver.resolve(domain, "MX")
        best = min(answers, key=lambda r: r.preference)
        return MxResult(
            ok=True,
            host=str(best.exchange).rstrip("."),
            priority=best.preference,
        )
    except Exception:
        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = timeout
            resolver.resolve(domain, "A")
            return MxResult(ok=True, host=domain, priority=0)
        except Exception as e:
            return MxResult(ok=False, error=f"no MX/A: {e}")
