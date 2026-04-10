from mailguard.checks.disposable import is_disposable
from mailguard.checks.free_provider import is_free_provider
from mailguard.checks.role import is_role_address
from mailguard.checks.typo import suggest_correction


def test_disposable_known():
    assert is_disposable("mailinator.com")
    assert is_disposable("yopmail.com")
    assert is_disposable("trashmail.com")


def test_disposable_unknown():
    assert not is_disposable("gmail.com")
    assert not is_disposable("mycompany.io")


def test_free_provider():
    assert is_free_provider("gmail.com")
    assert is_free_provider("yahoo.com")
    assert is_free_provider("outlook.com")
    assert not is_free_provider("stripe.com")


def test_role_based():
    assert is_role_address("info@acme.com")
    assert is_role_address("admin@acme.com")
    assert is_role_address("support@acme.com")
    assert is_role_address("sales+stripe@acme.com")  # strip +tag
    assert not is_role_address("jane.doe@acme.com")


def test_typo_suggestion_gmail():
    assert suggest_correction("gmial.com") == "gmail.com"
    assert suggest_correction("gmaill.com") == "gmail.com"


def test_typo_suggestion_yahoo():
    assert suggest_correction("yhoo.com") == "yahoo.com"


def test_typo_no_suggestion_for_valid():
    assert suggest_correction("gmail.com") is None
    assert suggest_correction("stripe.com") is None


def test_typo_no_false_positive_on_short_corporate():
    """Regression: real-world false positives found on the Recko list."""
    # Short corporate domains must NEVER be "corrected" to me.com / mac.com / etc.
    assert suggest_correction("pg.com") is None       # Procter & Gamble
    assert suggest_correction("nc.com") is None
    assert suggest_correction("hm.com") is None       # H&M
    assert suggest_correction("wsj.com") is None      # Wall Street Journal
    assert suggest_correction("tjx.com") is None      # TJX
    assert suggest_correction("pwc.com") is None      # PwC
    assert suggest_correction("merz.com") is None


def test_typo_regional_variants_are_valid():
    """yahoo.com.vn / yahoo.com.au / hotmail.de must not get 'corrected'."""
    assert suggest_correction("yahoo.com.vn") is None
    assert suggest_correction("yahoo.com.au") is None
    assert suggest_correction("hotmail.de") is None
    assert suggest_correction("live.co.uk") is None
