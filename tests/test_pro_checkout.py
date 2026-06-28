import pytest

from shared.pro_checkout import PRO_CHECKOUT_MONTHLY, pro_checkout_enabled, public_checkout_urls


@pytest.mark.parametrize(
    "value,expected", [("0", False), ("1", True), ("true", True), ("yes", True), ("on", True), ("", False)]
)
def test_pro_checkout_enabled_env(monkeypatch, value, expected):
    if value:
        monkeypatch.setenv("BAKLOG_PRO_CHECKOUT", value)
    else:
        monkeypatch.delenv("BAKLOG_PRO_CHECKOUT", raising=False)
    assert pro_checkout_enabled() is expected


def test_public_checkout_urls_empty_when_disabled(monkeypatch):
    monkeypatch.delenv("BAKLOG_PRO_CHECKOUT", raising=False)
    assert public_checkout_urls() == {"monthly": "", "yearly": ""}


def test_public_checkout_urls_populated_when_enabled(monkeypatch):
    monkeypatch.setenv("BAKLOG_PRO_CHECKOUT", "1")
    urls = public_checkout_urls()
    assert urls["monthly"] == PRO_CHECKOUT_MONTHLY
    assert urls["yearly"]
