import pytest

from mailguard.core import validate, validate_bulk


@pytest.mark.asyncio
async def test_validate_bad_syntax():
    r = await validate("notanemail")
    assert not r.is_valid
    assert r.verdict == "undeliverable"
    assert not r.syntax_ok


@pytest.mark.asyncio
async def test_validate_disposable():
    r = await validate("test@mailinator.com")
    assert r.disposable
    assert r.verdict == "undeliverable"


@pytest.mark.asyncio
async def test_validate_role_based():
    # Use a domain that should resolve; we're only testing role detection
    r = await validate("info@example.com")
    assert r.role_based


@pytest.mark.asyncio
async def test_validate_typo():
    r = await validate("jane@gmial.com")
    assert r.typo_suggestion == "gmail.com"


@pytest.mark.asyncio
async def test_validate_bulk_fault_tolerant():
    emails = [
        "jane@gmail.com",
        "",  # empty
        "notanemail",
        "info@mailinator.com",
        "foo@gmial.com",
    ]
    results = await validate_bulk(emails, concurrency=5, timeout=5.0)
    assert len(results) == len(emails)
    # No exceptions should have escaped
    assert all(hasattr(r, "verdict") for r in results)


@pytest.mark.asyncio
async def test_validate_never_raises():
    """Any input should return a ValidationResult, never throw."""
    weird_inputs = [
        "",
        "@",
        "@@@",
        "a" * 1000,
        "foo@" + "x" * 500 + ".com",
        "\x00",
    ]
    for w in weird_inputs:
        r = await validate(w, timeout=3.0)
        assert r is not None
        assert isinstance(r.errors, list)
