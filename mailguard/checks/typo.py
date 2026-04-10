"""Typo detection via Damerau-Levenshtein against a curated list of common domains.

Catches gmial.com → gmail.com, yaho.com → yahoo.com, etc. Extremely high-ROI
for form capture because it recovers otherwise-lost leads.
"""
from __future__ import annotations

COMMON_DOMAINS: tuple[str, ...] = (
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
    "zoho.com", "mail.com", "gmx.com", "fastmail.com", "yandex.com",
    "rediffmail.com", "qq.com", "163.com", "naver.com",
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

    Returns None if no suggestion (already a known domain, or distance too large).
    """
    d = domain.lower().strip(".")
    if d in COMMON_DOMAINS:
        return None
    best: tuple[int, str] | None = None
    for candidate in COMMON_DOMAINS:
        dist = _dl_distance(d, candidate, max_dist)
        if dist <= max_dist and (best is None or dist < best[0]):
            best = (dist, candidate)
    return best[1] if best else None
