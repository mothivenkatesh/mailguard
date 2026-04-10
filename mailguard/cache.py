"""Persistent cache for DNS and SMTP verdicts.

Uses SQLite (stdlib only — no new dependency) at ``~/.mailguard/cache.db``.
Values are stored with a TTL and a namespace so different layers don't
collide. Thread-safe; each call opens a short-lived connection.

Disable by setting env var ``MAILGUARD_NO_CACHE=1``.
Override location with ``MAILGUARD_CACHE_PATH=/custom/path.db``.

Typical TTLs:
    mx            86_400   (1 day)  — MX records rarely change
    catch_all     604_800  (7 days) — catch-all behaviour is stable
    smtp          3_600    (1 hour) — be conservative, mailboxes churn
    dbl           3_600    (1 hour) — reputation data moves
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

_DISABLED = os.environ.get("MAILGUARD_NO_CACHE") == "1"


def _db_path() -> Path:
    env = os.environ.get("MAILGUARD_CACHE_PATH")
    if env:
        return Path(env)
    home = Path.home() / ".mailguard"
    home.mkdir(parents=True, exist_ok=True)
    return home / "cache.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0, isolation_level=None)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            namespace TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT NOT NULL,
            expires   REAL NOT NULL,
            PRIMARY KEY (namespace, key)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires)")
    return conn


def get(namespace: str, key: str) -> Any | None:
    """Return cached value, or None if missing / expired / cache disabled."""
    if _DISABLED:
        return None
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT value, expires FROM cache WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return None
            value, expires = row
            if expires < time.time():
                conn.execute(
                    "DELETE FROM cache WHERE namespace=? AND key=?",
                    (namespace, key),
                )
                return None
            return json.loads(value)
    except (sqlite3.Error, json.JSONDecodeError, OSError):
        return None  # cache failure must never break validation


def put(namespace: str, key: str, value: Any, ttl: float) -> None:
    """Store a value with a TTL in seconds. Silent on failure."""
    if _DISABLED:
        return
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache(namespace, key, value, expires) "
                "VALUES (?, ?, ?, ?)",
                (namespace, key, json.dumps(value), time.time() + ttl),
            )
    except (sqlite3.Error, TypeError, OSError):
        pass  # never crash the pipeline because the cache failed


def purge_expired() -> int:
    """Delete expired rows. Returns number of rows deleted."""
    if _DISABLED:
        return 0
    try:
        with _connect() as conn:
            cur = conn.execute("DELETE FROM cache WHERE expires < ?", (time.time(),))
            return cur.rowcount or 0
    except sqlite3.Error:
        return 0


def clear(namespace: str | None = None) -> None:
    """Wipe one namespace, or the entire cache."""
    try:
        with _connect() as conn:
            if namespace:
                conn.execute("DELETE FROM cache WHERE namespace=?", (namespace,))
            else:
                conn.execute("DELETE FROM cache")
    except sqlite3.Error:
        pass
