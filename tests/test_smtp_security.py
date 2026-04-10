"""Security tests for the SMTP probe — regression coverage for CRLF injection."""
from __future__ import annotations

import pytest

from mailguard.checks.smtp_check import (
    UnsafeSmtpArgument,
    _sanitize_smtp_token,
    _validate_email_for_probe,
    _validate_hostname,
    smtp_probe,
)


@pytest.mark.parametrize(
    "bad",
    [
        "foo@bar.com\r\nMAIL FROM:<attacker@evil",  # classic CRLF smuggling
        "foo@bar.com\rINJECT",
        "foo@bar.com\nINJECT",
        "foo@bar.com\x00null",
        "foo\x1b[31m@bar.com",  # ANSI escape
        "foo@bar.com>extra",  # angle bracket escape of envelope
        "<injected@foo.com>",
        "",
        "a" * 300 + "@bar.com",  # too long
        "foo@" + "b" * 300 + ".com",  # domain too long
        "noatsign",
    ],
)
def test_validate_email_rejects_malicious(bad: str):
    with pytest.raises(UnsafeSmtpArgument):
        _validate_email_for_probe(bad)


def test_validate_email_accepts_normal():
    assert _validate_email_for_probe("jane.doe@example.com") == "jane.doe@example.com"
    assert _validate_email_for_probe("a+b@c.co") == "a+b@c.co"


@pytest.mark.parametrize(
    "bad",
    [
        "host\r\n",
        "host name",
        "host;ls",
        "host$(whoami)",
        "",
        "a" * 300,
    ],
)
def test_validate_hostname_rejects_malicious(bad: str):
    with pytest.raises(UnsafeSmtpArgument):
        _validate_hostname(bad)


def test_validate_hostname_accepts_normal():
    assert _validate_hostname("mx.example.com") == "mx.example.com"
    assert _validate_hostname("mail-01.example.co.uk") == "mail-01.example.co.uk"


@pytest.mark.asyncio
async def test_smtp_probe_returns_none_on_unsafe_input():
    """Injection attempt must return None without opening a socket."""
    result = await smtp_probe(
        "foo@bar.com\r\nMAIL FROM:<evil", "mx.example.com", timeout=1.0
    )
    assert result is None


@pytest.mark.asyncio
async def test_smtp_probe_returns_none_on_unsafe_host():
    result = await smtp_probe("foo@bar.com", "mx.example.com\r\nINJECT", timeout=1.0)
    assert result is None
