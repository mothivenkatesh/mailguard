"""Tests for the persistent SQLite cache."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from mailguard import cache


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAILGUARD_CACHE_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("MAILGUARD_NO_CACHE", raising=False)
    yield
    cache.clear()


def test_put_and_get(tmp_cache):
    cache.put("test", "key1", {"a": 1}, ttl=60)
    assert cache.get("test", "key1") == {"a": 1}


def test_missing_returns_none(tmp_cache):
    assert cache.get("test", "missing") is None


def test_expiry(tmp_cache):
    cache.put("test", "k", "v", ttl=0.1)
    time.sleep(0.2)
    assert cache.get("test", "k") is None


def test_namespace_isolation(tmp_cache):
    cache.put("ns1", "k", "v1", ttl=60)
    cache.put("ns2", "k", "v2", ttl=60)
    assert cache.get("ns1", "k") == "v1"
    assert cache.get("ns2", "k") == "v2"


def test_disabled_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAILGUARD_NO_CACHE", "1")
    monkeypatch.setenv("MAILGUARD_CACHE_PATH", str(tmp_path / "test.db"))
    # Reload the module so the env var is picked up
    import importlib

    from mailguard import cache as c
    importlib.reload(c)
    c.put("test", "k", "v", ttl=60)
    assert c.get("test", "k") is None
    # Reset
    monkeypatch.delenv("MAILGUARD_NO_CACHE")
    importlib.reload(c)


def test_clear_namespace(tmp_cache):
    cache.put("ns1", "a", "1", ttl=60)
    cache.put("ns2", "b", "2", ttl=60)
    cache.clear("ns1")
    assert cache.get("ns1", "a") is None
    assert cache.get("ns2", "b") == "2"
