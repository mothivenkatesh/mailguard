"""Async SMTP RCPT probe.

WARNING: port 25 is blocked on most residential ISPs, Google Colab, and many
cloud providers. This check is OPTIONAL and degrades gracefully to ``None``
(unknown) rather than False when the network blocks it — so a blocked probe
does not falsely mark addresses as undeliverable.

We also avoid sending data / quitting cleanly to minimise chances of being
flagged by receiving MTAs. One probe per domain per run is recommended —
callers should deduplicate upstream.
"""
from __future__ import annotations

import asyncio

DEFAULT_HELO = "mailguard.local"
DEFAULT_MAIL_FROM = "probe@mailguard.local"


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
    (port blocked, timeout, greylisted, etc.). Callers should treat None as
    "no signal" rather than failure.
    """
    if not mx_host:
        return None
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
        writer.write((cmd + "\r\n").encode())
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
        # 4xx = temporary (greylisting) → unknown
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
