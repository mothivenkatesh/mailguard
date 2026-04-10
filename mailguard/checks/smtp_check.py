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
import ssl
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


async def _read_line(reader: asyncio.StreamReader, timeout: float) -> str:
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    return line.decode(errors="replace").strip()


async def _read_multiline(reader: asyncio.StreamReader, timeout: float) -> list[str]:
    """Read a multi-line SMTP response (each line after the first starts with '-')."""
    lines: list[str] = []
    while True:
        line = await _read_line(reader, timeout)
        lines.append(line)
        if len(line) < 4 or line[3] != "-":
            break
    return lines


async def smtp_probe(
    email: str,
    mx_host: str,
    *,
    timeout: float = 10.0,
    helo: str = DEFAULT_HELO,
    mail_from: str = DEFAULT_MAIL_FROM,
    use_starttls: bool = True,
) -> bool | None:
    """Return True/False if the MX accepts/rejects RCPT, or None if unknowable.

    If ``use_starttls`` is True (default) and the MX advertises STARTTLS in
    its EHLO response, we upgrade the connection before sending MAIL FROM.
    Some corporate MTAs require TLS before any envelope commands.

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
        return None

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25), timeout=timeout
        )
    except (OSError, asyncio.TimeoutError):
        return None

    async def _cmd(cmd: str) -> list[str]:
        assert "\r" not in cmd and "\n" not in cmd, "smtp command contains newline"
        writer.write((cmd + "\r\n").encode("ascii", errors="strict"))
        await writer.drain()
        return await _read_multiline(reader, timeout)

    try:
        banner = await _read_line(reader, timeout)
        if not banner.startswith("2"):
            return None

        # Prefer EHLO so we can see extensions (STARTTLS, PIPELINING, etc.)
        ehlo_resp = await _cmd(f"EHLO {helo}")
        if not ehlo_resp[0].startswith("2"):
            # Some ancient MTAs only speak HELO
            helo_resp = await _cmd(f"HELO {helo}")
            if not helo_resp[0].startswith("2"):
                return None
            extensions: list[str] = []
        else:
            extensions = [line[4:].strip().upper() for line in ehlo_resp[1:]]

        # Upgrade to STARTTLS if advertised and requested
        if use_starttls and any(ext.startswith("STARTTLS") for ext in extensions):
            try:
                tls_resp = await _cmd("STARTTLS")
                if tls_resp[0].startswith("2"):
                    ssl_ctx = ssl.create_default_context()
                    # Some MX certs don't match the hostname we connected to
                    # (they use the provider's wildcard cert). Be permissive
                    # on hostname since we're only probing, not sending.
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                    await asyncio.wait_for(
                        writer.start_tls(ssl_ctx, server_hostname=mx_host),
                        timeout=timeout,
                    )
                    # Re-issue EHLO after STARTTLS (required by RFC 3207)
                    await _cmd(f"EHLO {helo}")
            except (asyncio.TimeoutError, ssl.SSLError, OSError):
                # TLS failed — the probe is unreliable from here, return None
                return None

        mail_resp = await _cmd(f"MAIL FROM:<{mail_from}>")
        if not mail_resp[0].startswith("2"):
            return None

        rcpt_resp = await _cmd(f"RCPT TO:<{email}>")
        code = rcpt_resp[0][:3] if rcpt_resp and len(rcpt_resp[0]) >= 3 else ""
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
