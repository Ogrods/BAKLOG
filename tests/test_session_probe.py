"""Reactive GOG session probes (auth/session_probe.py)."""

from __future__ import annotations

from unittest.mock import patch

from auth.session_probe import (
    PROBEABLE_QUIET,
    probe_browser_session,
    probe_epic_session_quiet,
    probe_gog_session,
    probe_gog_session_quiet,
    probe_itad_session_quiet,
    probe_itch_session_quiet,
    probe_provider_quiet,
    probe_steam_session_quiet,
    probe_xbox_wishlist_session,
)
from gog_client import GOG_AUTH_MESSAGE, GogAuthError


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


class TestQuietProbes:
    def test_probeable_quiet_set(self) -> None:
        assert PROBEABLE_QUIET == frozenset({"gog", "epic", "steam", "itch", "itad"})

    def test_gog_quiet_ok(self) -> None:
        with patch("auth.session_probe.GogClient") as cls:
            cls.return_value.validate_session.return_value = True
            assert probe_gog_session_quiet("token") == "ok"

    def test_gog_quiet_auth_fail(self) -> None:
        with patch("auth.session_probe.GogClient") as cls:
            cls.return_value.validate_session.side_effect = GogAuthError(GOG_AUTH_MESSAGE)
            assert probe_gog_session_quiet("token") == "auth_fail"

    def test_gog_quiet_empty_cookie(self) -> None:
        assert probe_gog_session_quiet("") == "auth_fail"

    def test_gog_quiet_unreachable(self) -> None:
        with patch("auth.session_probe.GogClient") as cls:
            cls.return_value.validate_session.side_effect = TimeoutError("slow")
            assert probe_gog_session_quiet("token") == "unreachable"

    def test_epic_quiet_ok(self) -> None:
        with patch("epic_client.EpicClient") as cls:
            inst = cls.return_value
            inst._load_session.return_value = {"refresh_token": "rt"}
            assert probe_epic_session_quiet() == "ok"
            inst.login.assert_called_once()

    def test_epic_quiet_no_refresh_token(self) -> None:
        with patch("epic_client.EpicClient") as cls:
            cls.return_value._load_session.return_value = {}
            assert probe_epic_session_quiet() == "auth_fail"

    def test_steam_quiet_ok(self) -> None:
        with patch(
            "auth.manager.resolve_env",
            side_effect=lambda k, **_: "x" if k == "STEAM_API_KEY" else "sid",
        ):
            with patch("auth.api_keys._validate_steam"):
                assert probe_steam_session_quiet() == "ok"

    def test_steam_quiet_missing_creds(self) -> None:
        with patch("auth.manager.resolve_env", return_value=""):
            assert probe_steam_session_quiet() == "auth_fail"

    def test_itch_quiet_maps_tri_state(self) -> None:
        from auth.api_keys import KEY_INVALID, KEY_UNREACHABLE, KEY_VALID

        with patch("auth.manager.resolve_env", return_value="k"):
            with patch("auth.api_keys.validate_itch_key", return_value=KEY_VALID):
                assert probe_itch_session_quiet() == "ok"
            with patch("auth.api_keys.validate_itch_key", return_value=KEY_INVALID):
                assert probe_itch_session_quiet() == "auth_fail"
            with patch("auth.api_keys.validate_itch_key", return_value=KEY_UNREACHABLE):
                assert probe_itch_session_quiet() == "unreachable"

    def test_itad_quiet_maps_tri_state(self) -> None:
        from auth.api_keys import KEY_INVALID, KEY_UNREACHABLE, KEY_VALID

        with patch("auth.manager.resolve_env", return_value="k"):
            with patch("auth.api_keys.validate_itad_key", return_value=KEY_VALID):
                assert probe_itad_session_quiet() == "ok"
            with patch("auth.api_keys.validate_itad_key", return_value=KEY_INVALID):
                assert probe_itad_session_quiet() == "auth_fail"
            with patch("auth.api_keys.validate_itad_key", return_value=KEY_UNREACHABLE):
                assert probe_itad_session_quiet() == "unreachable"

    def test_probe_provider_quiet_routes(self) -> None:
        with patch("auth.session_probe.probe_gog_session_quiet", return_value="ok") as mock:
            with patch("auth.manager.resolve_env", return_value="cookie"):
                assert probe_provider_quiet("gog") == "ok"
        mock.assert_called_once_with("cookie")
