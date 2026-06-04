"""Reactive GOG session probes (auth/session_probe.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from auth.session_probe import (
    probe_browser_session,
    probe_gog_session,
    probe_xbox_wishlist_session,
)
from gog_client import GogAuthError, GOG_AUTH_MESSAGE


class TestProbeGogSession:
    def test_empty_cookie(self) -> None:
        err = probe_gog_session("")
        assert err is not None
        assert "No GOG session" in err

    def test_ok_when_validate_succeeds(self) -> None:
        with patch("auth.session_probe.GogClient") as cls:
            cls.return_value.validate_session.return_value = True
            assert probe_gog_session("token") is None

    def test_error_when_validate_raises(self) -> None:
        with patch("auth.session_probe.GogClient") as cls:
            cls.return_value.validate_session.side_effect = GogAuthError(GOG_AUTH_MESSAGE)
            err = probe_gog_session("token")
        assert err == GOG_AUTH_MESSAGE

    def test_probe_browser_session_routes_gog(self) -> None:
        with patch("auth.session_probe.probe_gog_session", return_value=None) as mock:
            assert probe_browser_session("gog", {"GOG_AL": "x"}) is None
        mock.assert_called_once_with("x")

    def test_probe_browser_session_unknown_provider(self) -> None:
        assert probe_browser_session("steam", {"STEAM_API_KEY": "k"}) is None


class TestProbeXboxWishlistSession:
    def test_signed_out_headless(self) -> None:
        state = {"user": {"isSignedIn": False}}
        with patch(
            "auth.xbox_wishlist_session.capture_xbox_wishlist_preloaded_state",
            return_value=state,
        ):
            err = probe_xbox_wishlist_session({"XBOX_WISHLIST_PROFILE": "ready"})
        assert err is not None
        assert "isSignedIn=false" in err

    def test_ok_when_headless_signed_in(self) -> None:
        state = {
            "user": {"isSignedIn": True},
            "pageRequestMetadata": {"/wishlist": {}},
        }
        with patch(
            "auth.xbox_wishlist_session.capture_xbox_wishlist_preloaded_state",
            return_value=state,
        ):
            assert probe_xbox_wishlist_session({"XBOX_WISHLIST_PROFILE": "ready"}) is None

    def test_capture_failure_surfaces(self) -> None:
        with patch(
            "auth.xbox_wishlist_session.capture_xbox_wishlist_preloaded_state",
            side_effect=RuntimeError("profile missing"),
        ):
            err = probe_xbox_wishlist_session({})
        assert err is not None
        assert "headless" in err.lower()

    def test_probe_browser_session_routes_xbox_wishlist(self) -> None:
        with patch(
            "auth.session_probe.probe_xbox_wishlist_session",
            return_value=None,
        ) as mock:
            assert probe_browser_session("xbox_wishlist", {"XBOX_WISHLIST_PROFILE": "ready"}) is None
        mock.assert_called_once()
