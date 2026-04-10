"""Detect free webmail providers (gmail, outlook, yahoo, ...).

Matters for GTM: a free-provider address is almost always a personal lead,
not a corporate contact, and changes ICP routing.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).parent.parent / "data" / "free_providers.txt"


@lru_cache(maxsize=1)
def _load() -> frozenset[str]:
    if not _DATA_FILE.exists():
        return frozenset()
    with _DATA_FILE.open("r", encoding="utf-8") as f:
        return frozenset(
            line.strip().lower()
            for line in f
            if line.strip() and not line.startswith("#")
        )


def is_free_provider(domain: str) -> bool:
    return domain.lower().strip(".") in _load()
