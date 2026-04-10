"""Tests for provider-specific trust adjustments."""
from mailguard.checks.providers import (
    mx_guarantee_bonus,
    provider_of,
    smtp_trust_multiplier,
)


def test_provider_gmail():
    assert provider_of("gmail.com") == "gmail"
    assert provider_of("googlemail.com") == "gmail"
    assert provider_of("GMAIL.COM") == "gmail"


def test_provider_outlook():
    assert provider_of("outlook.com") == "outlook"
    assert provider_of("hotmail.com") == "outlook"
    assert provider_of("live.com") == "outlook"
    assert provider_of("msn.com") == "outlook"


def test_provider_yahoo():
    assert provider_of("yahoo.com") == "yahoo"
    assert provider_of("yahoo.com.vn") == "yahoo"
    assert provider_of("ymail.com") == "yahoo"


def test_provider_icloud():
    assert provider_of("icloud.com") == "icloud"
    assert provider_of("me.com") == "icloud"
    assert provider_of("mac.com") == "icloud"


def test_provider_none_for_corporate():
    assert provider_of("stripe.com") is None
    assert provider_of("openai.com") is None


def test_smtp_trust_multiplier():
    assert smtp_trust_multiplier("gmail") == 0.4
    assert smtp_trust_multiplier("outlook") == 0.4
    assert smtp_trust_multiplier(None) == 1.0


def test_mx_guarantee_bonus():
    assert mx_guarantee_bonus("gmail") == 5
    assert mx_guarantee_bonus(None) == 0
