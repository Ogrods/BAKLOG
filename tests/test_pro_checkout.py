"""Polar checkout URL gating (beta vs public rollout)."""

from __future__ import annotations

import pytest

from shared.pro_checkout import (
    PRO_CHECKOUT_MONTHLY,
    PRO_PORTAL_URL,
    polar_portal_url,
    pro_checkout_enabled,
    public_checkout_urls,
)


def test_polar_portal_url_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKLOG_POLAR_PORTAL_URL", raising=False)
    assert polar_portal_url() == PRO_PORTAL_URL == "https://polar.sh/baklog/portal"
    monkeypatch.setenv("BAKLOG_POLAR_PORTAL_URL", "https://example.test/portal")
    assert polar_portal_url() == "https://example.test/portal"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("off", False),
        ("", True),
    ],
)
def test_pro_checkout_enabled_env(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    if value:
        monkeypatch.setenv("BAKLOG_PRO_CHECKOUT", value)
    else:
        monkeypatch.delenv("BAKLOG_PRO_CHECKOUT", raising=False)
    assert pro_checkout_enabled() is expected


def test_public_checkout_urls_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_PRO_CHECKOUT", "0")
    assert public_checkout_urls() == {"monthly": "", "yearly": ""}


def test_checkout_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKLOG_PRO_CHECKOUT", raising=False)
    assert public_checkout_urls()["monthly"] == PRO_CHECKOUT_MONTHLY


def test_public_checkout_urls_populated_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_PRO_CHECKOUT", "1")
    urls = public_checkout_urls()
    assert urls["monthly"] == PRO_CHECKOUT_MONTHLY
    assert urls["yearly"]
