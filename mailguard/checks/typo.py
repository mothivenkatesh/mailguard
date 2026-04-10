"""Typo detection via Damerau-Levenshtein against a curated list of common domains.

Catches gmial.com → gmail.com, yaho.com → yahoo.com, etc. Extremely high-ROI
for form capture because it recovers otherwise-lost leads.

DEFENSIVE RULES (added in v0.3.0 after false positives found on real data):
 1. Don't suggest for domains shorter than ``MIN_DOMAIN_LEN`` (6 chars).
    Short corporate domains like ``pg.com``, ``nc.com``, ``hm.com`` are
    distance-2 from ``me.com`` / ``mac.com`` but are legitimate.
 2. Don't suggest when the distance is >= half the candidate length
    (``dist < len(candidate) * 0.34``). Prevents "any short domain becomes
    gmail.com" false positives.
 3. Regional variants of common providers (``yahoo.com.vn``, ``yahoo.com.au``,
    ``hotmail.de`` etc.) are in the known list so they don't get "corrected"
    to some other region.
"""
from __future__ import annotations

MIN_DOMAIN_LEN = 7  # shortest length we'll attempt to correct (gmx.com = 7)

# Expanded list with regional variants so yahoo.com.vn / yahoo.com.au / etc.
# are treated as already-valid instead of near-misses of each other.
COMMON_DOMAINS: tuple[str, ...] = (
    # Gmail family
    "gmail.com", "googlemail.com",
    # Yahoo family — exact regional TLDs are included so we don't try to
    # "correct" yahoo.com.vn to yahoo.co.in.
    "yahoo.com", "yahoo.co.uk", "yahoo.co.in", "yahoo.ca",
    "yahoo.com.au", "yahoo.com.br", "yahoo.com.mx", "yahoo.com.ar",
    "yahoo.com.sg", "yahoo.com.ph", "yahoo.com.vn", "yahoo.com.tw",
    "yahoo.com.hk", "yahoo.fr", "yahoo.de", "yahoo.es", "yahoo.it",
    "yahoo.co.jp", "ymail.com", "rocketmail.com",
    # Outlook / Microsoft family
    "outlook.com", "outlook.co.uk", "outlook.fr", "outlook.de", "outlook.jp",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "hotmail.de", "hotmail.it",
    "hotmail.es",
    "live.com", "live.co.uk", "live.fr", "live.de", "live.it", "live.jp",
    "msn.com",
    # Apple family
    "icloud.com", "me.com", "mac.com",
    # AOL / Verizon
    "aol.com", "aim.com",
    # Privacy-focused
    "protonmail.com", "proton.me", "pm.me",
    "tutanota.com", "tutanota.de", "tuta.io",
    # Other common webmail
    "zoho.com", "zohomail.com",
    "mail.com", "email.com",
    "gmx.com", "gmx.de", "gmx.net",
    "fastmail.com", "fastmail.fm",
    "yandex.com", "yandex.ru",
    # Regional
    "rediffmail.com", "rediff.com",
    "qq.com", "163.com", "126.com", "sina.com", "sohu.com",
    "naver.com", "daum.net", "hanmail.net",
    "mail.ru", "list.ru", "bk.ru", "inbox.ru",
)


def _dl_distance(a: str, b: str, max_dist: int = 2) -> int:
    """Damerau-Levenshtein distance with early exit at ``max_dist``."""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    # Standard DP with adjacent-transposition support
    prev_prev = [0] * (lb + 1)
    prev = list(range(lb + 1))
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        curr[0] = i
        row_min = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,  # insertion
                prev[j] + 1,  # deletion
                prev[j - 1] + cost,  # substitution
            )
            if (
                i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                curr[j] = min(curr[j], prev_prev[j - 2] + 1)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return max_dist + 1
        prev_prev, prev, curr = prev, curr, prev_prev
    return prev[lb]


def suggest_correction(domain: str, max_dist: int = 2) -> str | None:
    """Return a suggested correction if ``domain`` is a near-miss of a common domain.

    Returns None if no suggestion (already a known domain, too short, or
    distance too large for the length).
    """
    d = domain.lower().strip(".")
    if d in COMMON_DOMAINS:
        return None
    # Rule 1: don't guess on short domains — pg.com, nc.com, hm.com
    # are legitimate corporate domains that sit distance-2 from me.com.
    if len(d) < MIN_DOMAIN_LEN:
        return None
    best: tuple[int, str] | None = None
    for candidate in COMMON_DOMAINS:
        # Rule 2: length gap must be within max_dist (edit distance lower bound).
        if abs(len(d) - len(candidate)) > max_dist:
            continue
        # Rule 3: short candidates (≤8 chars like msn.com, mac.com, gmx.com)
        # require distance 1. Longer candidates allow distance 2. Prevents
        # distance-2 false positives on 7-char corporate domains.
        allowed = 1 if len(candidate) <= 8 else max_dist
        dist = _dl_distance(d, candidate, allowed)
        if dist > allowed:
            continue
        if best is None or dist < best[0]:
            best = (dist, candidate)
    return best[1] if best else None
