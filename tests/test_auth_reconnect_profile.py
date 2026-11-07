from __future__ import annotations

from unittest.mock import patch

from auth.manager import PRESERVE_PROFILE_ON_RECONNECT, _should_clear_on_reconnect


def test_epic_wishlist_preserves_profile_on_reconnect() -> None:
    assert _should_clear_on_reconnect("epic_wishlist") is False


def test_epic_library_preserves_profile_on_reconnect() -> None:
    assert _should_clear_on_reconnect("epic") is False


def test_gog_clears_profile_on_reconnect() -> None:
    assert _should_clear_on_reconnect("gog") is True


def test_epic_wishlist_in_preserve_set() -> None:
    assert "epic_wishlist" in PRESERVE_PROFILE_ON_RECONNECT


def test_epic_library_in_preserve_set() -> None:
    assert "epic" in PRESERVE_PROFILE_ON_RECONNECT


def test_epic_wishlist_clears_profile_when_disconnected() -> None:
    from auth.manager import start_browser_auth

    def run_inline(*_a, **kwargs):
        target = kwargs.get("target")

        class _T:
            def start(self) -> None:
                if target:
                    target()

        return _T()

    with (
        patch("auth.manager._provider_state", return_value="disconnected"),
        patch("auth.manager.clear_browser_session") as clear_mock,
        patch("auth.cdp_browser.ensure_chromium_executable", return_value=None),
        patch("auth.manager.run_browser_auth", return_value={"ok": "1"}),
        patch("auth.session_probe.probe_browser_session", return_value=None),
        patch("auth.manager.mark_connected"),
        patch("auth.manager.threading.Thread", side_effect=run_inline),
    ):
        start_browser_auth("epic_wishlist", fresh=False)

    clear_mock.assert_called_once_with("epic_wishlist")
