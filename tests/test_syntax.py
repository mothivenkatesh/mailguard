from mailguard.checks.syntax import check_syntax


def test_valid_email():
    r = check_syntax("jane.doe@example.com")
    assert r.ok
    assert r.domain == "example.com"
    assert r.local == "jane.doe"


def test_valid_email_normalization():
    r = check_syntax("  JANE@EXAMPLE.COM  ")
    assert r.ok
    assert r.domain == "example.com"


def test_invalid_no_at():
    r = check_syntax("notanemail")
    assert not r.ok


def test_invalid_empty():
    r = check_syntax("")
    assert not r.ok


def test_invalid_double_at():
    r = check_syntax("foo@@bar.com")
    assert not r.ok
