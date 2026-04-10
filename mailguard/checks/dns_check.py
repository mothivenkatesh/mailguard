"""Async DNS / MX resolution with persistent cache and graceful fallback."""
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


@dataclass
class MxResult:
    ok: bool
    host: str = ""
    priority: int = 0
    error: str | None = None


# Keep an in-process dict on top of the persistent cache so repeated lookups
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

    result = await _resolve_async(domain, timeout) if aiodns else _resolve_sync(domain, timeout)
    _mem[domain] = result
    if result.ok:
        cache.put(CACHE_NS, domain, asdict(result), ttl=CACHE_TTL)
    else:
        # Negative cache with shorter TTL — bad domains sometimes come back
        cache.put(CACHE_NS, domain, asdict(result), ttl=3600)
    return result


async def _resolve_async(domain: str, timeout: float) -> MxResult:
    resolver = aiodns.DNSResolver(timeout=timeout)
    try:
        records = await asyncio.wait_for(resolver.query(domain, "MX"), timeout=timeout)
        if records:
            best = min(records, key=lambda r: r.priority)
            return MxResult(ok=True, host=best.host.rstrip("."), priority=best.priority)
    except Exception:
        pass
    # Fallback: A record — some domains accept mail on the apex
    try:
        await asyncio.wait_for(resolver.query(domain, "A"), timeout=timeout)
        return MxResult(ok=True, host=domain, priority=0)
    except Exception as e:
        return MxResult(ok=False, error=f"no MX/A: {e}")


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
