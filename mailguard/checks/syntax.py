"""RFC 5322 / 6531 syntax validation using email-validator (no regex)."""
from __future__ import annotations

from dataclasses import dataclass

try:
    from email_validator import EmailNotValidError, validate_email
except ImportError:  # pragma: no cover
    validate_email = None  # type: ignore[assignment]
    EmailNotValidError = Exception  # type: ignore[assignment,misc]


@dataclass
class SyntaxResult:
    ok: bool
    normalized: str = ""
    domain: str = ""
    local: str = ""
    error: str | None = None


def check_syntax(email: str) -> SyntaxResult:
    """Validate RFC-compliant syntax and return the normalized form.

    We do NOT do DNS deliverability here — that's a separate layer so we
    can keep this pure and fast.
    """
    if not email or "@" not in email:
        return SyntaxResult(ok=False, error="missing @ or empty")
    if validate_email is None:
        # Fallback: minimal check if dependency missing
        local, _, domain = email.rpartition("@")
        if not local or not domain or "." not in domain:
            return SyntaxResult(ok=False, error="invalid format")
        return SyntaxResult(
            ok=True,
            normalized=email.lower().strip(),
            domain=domain.lower(),
            local=local,
        )
    try:
        info = validate_email(email, check_deliverability=False)
        return SyntaxResult(
            ok=True,
            normalized=info.normalized,
            domain=info.domain.lower(),
            local=info.local_part,
        )
    except EmailNotValidError as e:
        return SyntaxResult(ok=False, error=str(e))
