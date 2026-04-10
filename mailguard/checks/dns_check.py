"""Async DNS / MX resolution with graceful fallback and caching."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache

try:
    import aiodns
except ImportError:  # pragma: no cover
    aiodns = None  # type: ignore[assignment]

try:
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None  # type: ignore[assignment]


@dataclass
class MxResult:
    ok: bool
    host: str = ""
    priority: int = 0
    error: str | None = None


_cache: dict[str, MxResult] = {}


async def resolve_mx(domain: str, *, timeout: float = 10.0) -> MxResult:
    """Resolve MX records for a domain, falling back to A/AAAA.

    Cached in-process so repeated lookups for the same domain are free.
    """
    domain = domain.lower().strip(".")
    if domain in _cache:
        return _cache[domain]

    result = await _resolve_async(domain, timeout) if aiodns else _resolve_sync(domain, timeout)
    _cache[domain] = result
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
            resolver.resolve(domain, "A")
            return MxResult(ok=True, host=domain, priority=0)
        except Exception as e:
            return MxResult(ok=False, error=f"no MX/A: {e}")


@lru_cache(maxsize=1)
def _warn_no_aiodns() -> None:
    import warnings

    warnings.warn(
        "aiodns not installed — DNS will run synchronously and be slower",
        stacklevel=2,
    )
