"""Provider-specific trust adjustments.

Gmail, Outlook, and Yahoo have known-unreliable SMTP RCPT behavior — they
often accept-all (or greylist) for privacy reasons, so a `2xx` RCPT response
is much weaker evidence than it would be from a corporate MTA. Conversely,
their MX infrastructure is rock-solid, so if DNS resolves the provider
itself, the domain is effectively guaranteed to route mail.

This module captures those provider-specific tweaks so the generic scoring
function doesn't need to care.
"""
from __future__ import annotations

# Provider detection by domain → behaviour class
GMAIL_DOMAINS: frozenset[str] = frozenset({"gmail.com", "googlemail.com"})
OUTLOOK_DOMAINS: frozenset[str] = frozenset({
    "outlook.com", "outlook.co.uk", "outlook.fr", "outlook.de",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "hotmail.de",
    "hotmail.it", "hotmail.es",
    "live.com", "live.co.uk", "live.fr", "live.de",
    "msn.com",
})
YAHOO_DOMAINS: frozenset[str] = frozenset({
    "yahoo.com", "yahoo.co.uk", "yahoo.co.in", "yahoo.ca",
    "yahoo.com.au", "yahoo.com.br", "yahoo.com.mx", "yahoo.com.ar",
    "yahoo.com.sg", "yahoo.com.ph", "yahoo.com.vn", "yahoo.com.tw",
    "yahoo.fr", "yahoo.de", "yahoo.es", "yahoo.it",
    "ymail.com", "rocketmail.com",
})
ICLOUD_DOMAINS: frozenset[str] = frozenset({"icloud.com", "me.com", "mac.com"})


def provider_of(domain: str) -> str | None:
    """Return the provider name for known big-three+apple providers.

    Returns:
        "gmail" | "outlook" | "yahoo" | "icloud" | None
    """
    d = domain.lower().strip(".")
    if d in GMAIL_DOMAINS:
        return "gmail"
    if d in OUTLOOK_DOMAINS:
        return "outlook"
    if d in YAHOO_DOMAINS:
        return "yahoo"
    if d in ICLOUD_DOMAINS:
        return "icloud"
    return None


def smtp_trust_multiplier(provider: str | None) -> float:
    """Return how much to trust a positive SMTP RCPT result for this provider.

    Big free providers often greylist or accept-all for privacy, so a 2xx
    from them is a weak signal. Corporate domains get full trust.

    1.0 = full trust, 0.0 = no trust.
    """
    if provider is None:
        return 1.0
    # Big free providers: treat positive SMTP as ~40% signal strength.
    # We still use it, but we don't let it push a score to deliverable
    # on its own.
    if provider in {"gmail", "outlook", "yahoo", "icloud"}:
        return 0.4
    return 1.0


def mx_guarantee_bonus(provider: str | None) -> int:
    """Extra score for MX belonging to a provider with rock-solid routing.

    If MX resolves to gmail/outlook/yahoo/icloud, we know the domain will
    route mail reliably even if we can't probe individual mailboxes.
    """
    return 5 if provider is not None else 0
