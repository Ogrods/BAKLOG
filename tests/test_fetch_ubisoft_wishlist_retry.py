"""Ubisoft wishlist fetch retry on transient navigation failure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def wishlist_mod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import fetchers.fetch_ubisoft_wishlist as mod

    profile = tmp_path / "ubisoft"
    profile.mkdir()
    monkeypatch.setattr(mod, "profile_dir", lambda _k: profile)
    monkeypatch.setattr(mod, "WISHLIST_URL", "https://example.test/wishlist")
    return mod


def test_fetch_wishlist_html_retries_once_on_transient_error(wishlist_mod, monkeypatch):
    calls = {"n": 0}

    def fake_launch(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("navigation timeout")
        ctx = MagicMock()
        page = MagicMock()
        page.title.return_value = "Wishlist"
        page.content.return_value = (
            '<div class="product-tile  wishlist-product-tile" data-pid="1"></div>'
            + "x" * 250_000
        )
        ctx.pages = [page]
        ctx.new_page.return_value = page
        return ctx

    monkeypatch.setattr(
        "auth.cdp_browser.launch_persistent_profile",
        fake_launch,
    )
    monkeypatch.setattr(
        "auth.cdp_browser.close_browser_bounded",
        lambda *_a, **_k: None,
    )

    title, html = wishlist_mod._fetch_wishlist_html(timeout_s=30)
    assert calls["n"] == 2
    assert title == "Wishlist"
    assert "wishlist-product-tile" in html


def test_fetch_wishlist_html_raises_after_two_failures(wishlist_mod, monkeypatch):
    def always_fail(*_a, **_k):
        raise TimeoutError("navigation timeout")

    monkeypatch.setattr(
        "auth.cdp_browser.launch_persistent_profile",
        always_fail,
    )
    monkeypatch.setattr(
        "auth.cdp_browser.close_browser_bounded",
        lambda *_a, **_k: None,
    )

    with pytest.raises(TimeoutError, match="navigation timeout"):
        wishlist_mod._fetch_wishlist_html(timeout_s=30)
