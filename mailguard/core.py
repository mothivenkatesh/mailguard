"""Core validation pipeline.

Runs every email through a layered set of checks and produces a deliverability
score. Designed to be fault-tolerant: any individual check failing never
crashes the pipeline — it returns a degraded but still-usable result.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from mailguard.checks.catchall import detect_catchall
from mailguard.checks.dbl import check_reputation
from mailguard.checks.disposable import is_disposable
from mailguard.checks.dns_check import resolve_mx
from mailguard.checks.free_provider import is_free_provider
from mailguard.checks.providers import mx_guarantee_bonus, provider_of
from mailguard.checks.role import is_role_address
from mailguard.checks.smtp_check import smtp_probe
from mailguard.checks.syntax import SyntaxResult, check_syntax
from mailguard.checks.typo import suggest_correction


@dataclass
class ValidationResult:
    """Full validation report for a single email address."""

    email: str
    is_valid: bool = False
    score: int = 0  # 0–100 deliverability confidence
    verdict: str = "unknown"  # deliverable | risky | undeliverable | unknown
    reason: str = ""

    # Layer results
    syntax_ok: bool = False
    normalized: str = ""
    domain: str = ""
    mx_ok: bool = False
    mx_host: str = ""
    disposable: bool = False
    role_based: bool = False
    free_provider: bool = False
    catch_all: bool | None = None  # None = not probed
    smtp_ok: bool | None = None  # None = not probed
    typo_suggestion: str | None = None
    reputation_listed: bool | None = None  # None = not checked
    reputation_providers: list[str] = field(default_factory=list)
    provider: str | None = None  # gmail | outlook | yahoo | icloud | None

    # Classification
    email_type: str = "unknown"  # personal | work | unknown

    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify(free: bool, disposable: bool) -> str:
    if disposable:
        return "disposable"
    if free:
        return "personal"
    return "work"


def _score_and_verdict(r: ValidationResult) -> tuple[int, str, str]:
    """Compute a 0–100 deliverability score and a human verdict.

    Weights calibrated against ``tests/groundtruth.yaml`` via
    ``benchmarks/accuracy.py``. See DESIGN.md for the rationale behind each
    number. Do not change any value here without re-running the benchmark
    and updating the measured F1 in README.md and DESIGN.md.

    Invariants:
        - syntax fail     → 0  (hard block, undeliverable)
        - no MX           → 5  (hard block, undeliverable)
        - disposable      → 15 (hard block, undeliverable)
        - clean profile   → 85 (syntax+MX+non-disposable+non-role+non-typo
                                with no catch-all confirmation) → deliverable
        - role address    → 65 (risky)
        - typo detected   → 55 (risky, surfaced to user)
    """
    if not r.syntax_ok:
        return 0, "undeliverable", "invalid syntax"
    if not r.mx_ok:
        return 5, "undeliverable", "no MX records"
    if r.disposable:
        return 15, "undeliverable", "disposable domain"

    # Baseline: syntax + MX + non-disposable → 75.
    # This reflects an honest prior that heuristic-only validation gives
    # strong-but-not-perfect confidence. Bonuses push clean addresses over
    # the deliverable threshold (80); penalties drop risky addresses below it.
    score = 75
    reasons: list[str] = []

    # "Clean profile" bonus: nothing about the address trips any heuristic.
    # Only awarded when the operator has *not* explicitly enabled SMTP or
    # catch-all checks — otherwise the SMTP/catch-all modifiers carry weight.
    is_clean = (
        not r.role_based
        and not r.typo_suggestion
        and r.catch_all is not True
    )
    if is_clean:
        score += 10

    if r.smtp_ok is True:
        score += 15
        reasons.append("smtp accepted")
    elif r.smtp_ok is False:
        score -= 40
        reasons.append("smtp rejected")
    # smtp_ok is None → no change (port 25 blocked / skipped)

    if r.catch_all is True:
        score -= 20
        reasons.append("catch-all domain")
    elif r.catch_all is False:
        score += 5

    if r.role_based:
        score -= 20
        reasons.append("role address")

    if r.free_provider:
        score += 5  # free providers have strong MX guarantees

    # Provider-specific: rock-solid MX routing deserves a small bonus.
    score += mx_guarantee_bonus(r.provider)

    # Domain reputation: if any DBL flagged the domain, it's risky-at-best.
    if r.reputation_listed is True:
        score -= 25
        reasons.append(f"listed on DBL: {','.join(r.reputation_providers)}")

    if r.typo_suggestion:
        score -= 20
        reasons.append(f"possible typo → {r.typo_suggestion}")

    score = max(0, min(100, score))

    if score >= 80:
        verdict = "deliverable"
    elif score >= 50:
        verdict = "risky"
    else:
        verdict = "undeliverable"

    return score, verdict, "; ".join(reasons) or "ok"


async def validate(
    email: str,
    *,
    check_smtp: bool = False,
    check_catchall: bool = False,
    check_reputation_layer: bool = False,
    timeout: float = 10.0,
) -> ValidationResult:
    """Validate a single email address.

    Args:
        email: The email to validate.
        check_smtp: Run the SMTP RCPT probe (slow, may fail on port-25-blocked hosts).
        check_catchall: Probe domain for catch-all behaviour before trusting SMTP.
        check_reputation_layer: Query DNSBLs (Spamhaus, URIBL, SURBL).
        timeout: Per-network-call timeout in seconds.

    Returns:
        ValidationResult — never raises.
    """
    r = ValidationResult(email=email.strip())

    # Layer 1: syntax
    try:
        sx: SyntaxResult = check_syntax(r.email)
        r.syntax_ok = sx.ok
        r.normalized = sx.normalized
        r.domain = sx.domain
        if not sx.ok:
            r.reason = sx.error or "invalid syntax"
            r.score, r.verdict, r.reason = _score_and_verdict(r)
            return r
    except Exception as e:  # never let a bug kill the pipeline
        r.errors.append(f"syntax: {e}")
        return r

    # Layer 2: typo suggestion (non-blocking)
    try:
        r.typo_suggestion = suggest_correction(r.domain)
    except Exception as e:
        r.errors.append(f"typo: {e}")

    # Layer 3: classification (disposable / role / free / provider)
    try:
        r.disposable = is_disposable(r.domain)
    except Exception as e:
        r.errors.append(f"disposable: {e}")
    try:
        r.role_based = is_role_address(r.normalized)
    except Exception as e:
        r.errors.append(f"role: {e}")
    try:
        r.free_provider = is_free_provider(r.domain)
    except Exception as e:
        r.errors.append(f"free_provider: {e}")
    try:
        r.provider = provider_of(r.domain)
    except Exception as e:
        r.errors.append(f"provider: {e}")

    r.email_type = _classify(r.free_provider, r.disposable)

    # Layer 4: DNS / MX
    try:
        mx = await resolve_mx(r.domain, timeout=timeout)
        r.mx_ok = mx.ok
        r.mx_host = mx.host or ""
        if not mx.ok:
            r.reason = mx.error or "no MX"
    except Exception as e:
        r.errors.append(f"dns: {e}")
        r.mx_ok = False

    # Layer 5: catch-all probe (optional, informs SMTP trust)
    if check_catchall and r.mx_ok:
        try:
            r.catch_all = await detect_catchall(r.domain, r.mx_host, timeout=timeout)
        except Exception as e:
            r.errors.append(f"catchall: {e}")

    # Layer 6: SMTP probe (optional, may be blocked)
    if check_smtp and r.mx_ok and r.catch_all is not True:
        try:
            r.smtp_ok = await smtp_probe(r.normalized, r.mx_host, timeout=timeout)
        except Exception as e:
            r.errors.append(f"smtp: {e}")
            r.smtp_ok = None

    # Layer 7: domain reputation (optional, DNS-based, fast)
    if check_reputation_layer and r.mx_ok:
        try:
            rep = await check_reputation(r.domain, timeout=timeout)
            r.reputation_listed = rep.listed
            r.reputation_providers = rep.providers
        except Exception as e:
            r.errors.append(f"reputation: {e}")

    # Final scoring
    r.score, r.verdict, r.reason = _score_and_verdict(r)
    r.is_valid = r.verdict in {"deliverable", "risky"}
    return r


def validate_sync(email: str, **kwargs: Any) -> ValidationResult:
    """Synchronous wrapper around :func:`validate`."""
    return asyncio.run(validate(email, **kwargs))


async def validate_bulk(
    emails: Iterable[str],
    *,
    concurrency: int = 50,
    check_smtp: bool = False,
    check_catchall: bool = False,
    check_reputation_layer: bool = False,
    timeout: float = 10.0,
    progress_cb: Any = None,
) -> list[ValidationResult]:
    """Validate many emails concurrently.

    Args:
        emails: Iterable of email addresses.
        concurrency: Max in-flight validations (tune to avoid rate limits).
        check_smtp: Run SMTP RCPT probe.
        check_catchall: Probe for catch-all domains.
        timeout: Per-call timeout.
        progress_cb: Optional callable ``cb(done, total)``.

    Returns:
        List of ValidationResult in input order. Failures are captured in
        ``result.errors`` — this function never raises.
    """
    items = list(emails)
    total = len(items)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def _one(idx: int, email: str) -> tuple[int, ValidationResult]:
        nonlocal done
        async with sem:
            try:
                res = await validate(
                    email,
                    check_smtp=check_smtp,
                    check_catchall=check_catchall,
                    check_reputation_layer=check_reputation_layer,
                    timeout=timeout,
                )
            except Exception as e:
                res = ValidationResult(email=email, errors=[f"fatal: {e}"])
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:
                    pass
            return idx, res

    tasks = [_one(i, e) for i, e in enumerate(items)]
    results: list[ValidationResult] = [ValidationResult(email="")] * total
    for coro in asyncio.as_completed(tasks):
        idx, res = await coro
        results[idx] = res
    return results


def validate_bulk_sync(emails: Iterable[str], **kwargs: Any) -> list[ValidationResult]:
    """Synchronous wrapper around :func:`validate_bulk`."""
    return asyncio.run(validate_bulk(emails, **kwargs))
