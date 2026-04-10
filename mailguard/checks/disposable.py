"""Disposable / temporary email domain detection.

The bundled list is a compact seed. For production use, the list can be
refreshed from the maintained ``disposable-email-domains`` repo on GitHub
via ``mailguard update-lists``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).parent.parent / "data" / "disposable_domains.txt"


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


def is_disposable(domain: str) -> bool:
    """Return True if the domain is a known disposable provider."""
    return domain.lower().strip(".") in _load()
