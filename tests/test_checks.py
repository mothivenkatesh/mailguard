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
    assert suggest_correction("gmai.com") == "gmail.com"


def test_typo_suggestion_yahoo():
    assert suggest_correction("yaho.com") == "yahoo.com"


def test_typo_no_suggestion_for_valid():
    assert suggest_correction("gmail.com") is None
    assert suggest_correction("stripe.com") is None  # too far from any common
