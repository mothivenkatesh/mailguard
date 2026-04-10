"""Async SMTP RCPT probe.

SECURITY: every value that is written to the socket is validated as a
single-line SMTP token. Any email or parameter containing CR, LF, NUL, or
other control characters is rejected before any bytes are sent to the MX —
this prevents SMTP command injection (CVE-style smuggling where an attacker
supplies ``foo@bar.com>\\r\\nMAIL FROM:<evil``).

WARNING: port 25 is blocked on most residential ISPs, Google Colab, and many
cloud providers. This check is OPTIONAL and degrades gracefully to ``None``
(unknown) rather than False when the network blocks it — so a blocked probe
does not falsely mark addresses as undeliverable.

Callers should deduplicate by domain upstream; receiving MTAs rate-limit and
blacklist aggressively when probed from a single source IP.
"""
from __future__ import annotations

import asyncio
import string

DEFAULT_HELO = "mailguard.local"
DEFAULT_MAIL_FROM = "probe@mailguard.local"

# Characters that must never appear in an SMTP command argument.
# CR (\r), LF (\n), NUL (\0) are the injection vectors; we also forbid the
# other C0 control chars and DEL as a belt-and-braces measure.
_FORBIDDEN = {chr(c) for c in range(0x00, 0x20)} | {chr(0x7F)}

# RFC 5321 section 4.5.3.1: max 64 for local part, max 255 for domain,
# max 256 for the full address in the RCPT TO argument envelope.
_MAX_LOCAL = 64
_MAX_DOMAIN = 255
_MAX_EMAIL = 256


class UnsafeSmtpArgument(ValueError):
    """Raised when an SMTP argument contains control characters or is too long."""


def _sanitize_smtp_token(value: str, *, field: str, max_len: int) -> str:
    """Reject any value that would allow SMTP command injection.

    We validate rather than escape: an email containing CRLF is never
    legitimate, so the right move is to refuse the probe entirely.
    """
    if not isinstance(value, str):
        raise UnsafeSmtpArgument(f"{field}: not a string")
    if not value:
        raise UnsafeSmtpArgument(f"{field}: empty")
    if len(value) > max_len:
        raise UnsafeSmtpArgument(f"{field}: exceeds {max_len} chars")
    bad = _FORBIDDEN & set(value)
    if bad:
        names = ", ".join(f"U+{ord(c):04X}" for c in sorted(bad))
        raise UnsafeSmtpArgument(f"{field}: contains control chars ({names})")
    # Angle brackets in the value would also break the <...> envelope we wrap it in.
    if "<" in value or ">" in value:
        raise UnsafeSmtpArgument(f"{field}: contains angle brackets")
    return value


def _validate_email_for_probe(email: str) -> str:
    """Split-and-validate an email so each half satisfies its length limit."""
    if "@" not in email:
        raise UnsafeSmtpArgument("email: missing @")
    if len(email) > _MAX_EMAIL:
        raise UnsafeSmtpArgument(f"email: exceeds {_MAX_EMAIL} chars")
    local, _, domain = email.rpartition("@")
    _sanitize_smtp_token(local, field="local", max_len=_MAX_LOCAL)
    _sanitize_smtp_token(domain, field="domain", max_len=_MAX_DOMAIN)
    return email


def _validate_hostname(host: str) -> str:
    """Host names must be plain ASCII, no whitespace, no control chars."""
    _sanitize_smtp_token(host, field="host", max_len=255)
    allowed = set(string.ascii_letters + string.digits + ".-_")
    bad = set(host) - allowed
    if bad:
        raise UnsafeSmtpArgument(f"host: invalid characters {bad!r}")
    return host


async def smtp_probe(
    email: str,
    mx_host: str,
    *,
    timeout: float = 10.0,
    helo: str = DEFAULT_HELO,
    mail_from: str = DEFAULT_MAIL_FROM,
) -> bool | None:
    """Return True/False if the MX accepts/rejects RCPT, or None if unknowable.

    None is a first-class result — it means "we could not complete the probe"
    (port blocked, timeout, greylisted, unsafe input, etc.). Callers should
    treat None as "no signal" rather than failure.
    """
    if not mx_host:
        return None

    # Refuse to put any user-controlled bytes on the wire without validation.
    try:
        email = _validate_email_for_probe(email)
        mx_host = _validate_hostname(mx_host)
        helo = _validate_hostname(helo)
        _validate_email_for_probe(mail_from)
    except UnsafeSmtpArgument:
        return None  # unsafe → treat as "no signal", not a silent success

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return None  # port blocked or unreachable → unknown, not failure

    async def _read() -> str:
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return line.decode(errors="replace").strip()

    async def _cmd(cmd: str) -> str:
        # By construction every caller below passes a pre-validated token, so
        # the string cannot contain CR/LF. We still assert for defence in depth.
        assert "\r" not in cmd and "\n" not in cmd, "smtp command contains newline"
        writer.write((cmd + "\r\n").encode("ascii", errors="strict"))
        await writer.drain()
        return await _read()

    try:
        banner = await _read()
        if not banner.startswith("2"):
            return None
        resp = await _cmd(f"HELO {helo}")
        if not resp.startswith("2"):
            return None
        resp = await _cmd(f"MAIL FROM:<{mail_from}>")
        if not resp.startswith("2"):
            return None
        resp = await _cmd(f"RCPT TO:<{email}>")
        code = resp[:3] if len(resp) >= 3 else ""
        if code.startswith("25"):
            return True
        if code.startswith(("55", "54")):
            return False
        # 4xx = temporary (greylisting / rate limit) → unknown
        return None
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return None
    finally:
        try:
            writer.write(b"QUIT\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
