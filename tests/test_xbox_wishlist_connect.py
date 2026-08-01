"""Xbox wishlist connect URL + SSR helpers."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from auth import runner as auth_runner
from auth.runner import _xbox_url_is_login, _xbox_url_on_wishlist


def test_xbox_url_on_wishlist_ignores_oauth_redirect_uri() -> None:
    oauth = (
        "https://login.live.com/oauth20_authorize.srf?client_id=abc"
        "&redirect_uri=https%3A%2F%2Fwww.xbox.com%2Fen-us%2Fwishlist"
    )
    assert _xbox_url_on_wishlist(oauth) is False
    assert _xbox_url_is_login(oauth) is True


def test_xbox_url_on_wishlist_matches_real_wishlist_path() -> None:
    assert _xbox_url_on_wishlist("https://www.xbox.com/en-us/wishlist") is True
    assert _xbox_url_on_wishlist("https://www.xbox.com/en-US/wishlist") is True
    assert _xbox_url_is_login("https://www.xbox.com/en-us/wishlist") is False


def test_xbox_has_msa_session_detects_wlssc_and_xb_tokens() -> None:
    class _Ctx:
        @staticmethod
        def cookies():
            return [{"name": "MUID", "domain": ".live.com"}]

    assert auth_runner._xbox_has_msa_session(_Ctx()) is False

    class _Ctx2:
        @staticmethod
        def cookies():
            return [
                {"name": "WLSSC", "domain": ".live.com"},
                {"name": "XBXXtkhttp%3A%2F%2Fxboxlive.com%2F", "domain": ".xbox.com"},
            ]

    assert auth_runner._xbox_has_msa_session(_Ctx2()) is True


def test_xbox_capture_uses_bounded_close_on_hang(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fetcher capture must not leave Chrome holding the profile after close hangs."""
    from auth import xbox_wishlist_session as xws

    profile = tmp_path / "xbox_wishlist"
    profile.mkdir()
    released: list[Path] = []

    class HangCtx:
        pages = []
        _proc = type("P", (), {"poll": staticmethod(lambda: None)})()

        def add_init_script(self, _s: str) -> None:
            return None

        def new_page(self):
            class P:
                def goto(self, *a, **k):
                    raise RuntimeError("stop early")

                def wait_for_timeout(self, _ms: int) -> None:
                    return None

                def content(self) -> str:
                    return ""

            return P()

        def close(self) -> None:
            time.sleep(5.0)

    monkeypatch.setattr(xws, "profile_dir", lambda _p: profile)
    monkeypatch.setattr(xws, "launch_persistent_profile", lambda *a, **k: HangCtx())
    monkeypatch.setattr(
        "auth.cdp_browser.pids_holding_chromium_profile",
        lambda _p: [111] if not released else [],
    )
    monkeypatch.setattr(
        "auth.cdp_browser.release_chromium_profile_lock",
        lambda p, wait_sec=3.0: released.append(Path(p)) or [111],
    )
    # Force short join via close_browser_bounded used by the module.
    real_bounded = xws.close_browser_bounded

    def _bounded(ctx, *, profile=None, join_timeout: float = 10.0):
        return real_bounded(ctx, profile=profile, join_timeout=0.05)

    monkeypatch.setattr(xws, "close_browser_bounded", _bounded)

    with pytest.raises(RuntimeError):
        xws.capture_xbox_wishlist_preloaded_state(timeout_s=1)
    assert released
