"""Role-based address detection (info@, admin@, support@, ...).

Role addresses are real and deliverable but rarely useful for GTM marketers —
engagement rates are close to zero and many ESPs treat them as low-quality.
"""
from __future__ import annotations

ROLE_PREFIXES: frozenset[str] = frozenset(
    {
        "abuse", "admin", "administrator", "billing", "compliance", "contact",
        "enquiries", "enquiry", "feedback", "finance", "ftp", "help", "hello",
        "hostmaster", "hr", "info", "inquiries", "inquiry", "investor",
        "investorrelations", "it", "jobs", "legal", "mail", "marketing",
        "media", "news", "newsletter", "no-reply", "noreply", "notifications",
        "office", "orders", "postmaster", "privacy", "press", "purchasing",
        "returns", "root", "sales", "security", "services", "spam",
        "subscribe", "support", "sysadmin", "team", "tech", "unsubscribe",
        "web", "webmaster", "welcome",
    }
)


def is_role_address(email: str) -> bool:
    local = email.split("@", 1)[0].lower().strip()
    # Strip +tags (gmail-style): sales+stripe@foo.com → sales
    local = local.split("+", 1)[0]
    return local in ROLE_PREFIXES
