"""Unit tests for CDP browser helpers; optional integration if Chrome/Edge exists.

Integration smoke test (requires Chrome or Edge installed locally):

    pytest tests/test_cdp_browser.py -m integration

Skip integration explicitly:

    BAKLOG_SKIP_CDP_INTEGRATION=1 pytest tests/test_cdp_browser.py -m integration

GitHub Actions: run the manual "CDP smoke" workflow after a suspected browser regression.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from auth.cdp_browser import (
    _BROWSER_LAUNCH_HINT,
    CdpContext,
    CdpPage,
    _cdp_websocket_error,
    _chromium_executable_candidates,
    _should_preserve_popup,
    auth_banner_init_script,
    find_chromium_executable,
    is_blank_browser_url,
    launch_persistent_profile,
)
from auth.runner import _cookie_header


class _FakePage:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self.is_closed = False


def _bare_context() -> CdpContext:
    """A CdpContext with no live browser — _send is stubbed per test."""
    return CdpContext.__new__(CdpContext)


class TestCookieHeader:
    def test_filters_by_domain(self) -> None:
        cookies = [
            {"name": "a", "value": "1", "domain": ".battle.net"},
            {"name": "b", "value": "2", "domain": "example.com"},
            {"name": "c", "value": "3", "domain": "store.steampowered.com"},
        ]
        assert _cookie_header(cookies, (".battle.net",)) == "a=1"

    def test_skips_empty_names(self) -> None:
        cookies = [{"name": "", "value": "x", "domain": "nintendo.com"}]
        assert _cookie_header(cookies, ("nintendo.com",)) == ""


class TestBlankUrl:
    @pytest.mark.parametrize(
        "url",
        ["", "about:blank", "chrome://newtab/"],
    )
    def test_blank_urls(self, url: str) -> None:
        assert is_blank_browser_url(url)

    def test_real_url_not_blank(self) -> None:
        assert not is_blank_browser_url("https://connect.ubisoft.com/logged-in.html")


class TestShouldPreservePopup:
    @pytest.mark.parametrize("url", ["", "about:blank", "chrome://newtab/"])
    def test_blank_preserves(self, url: str) -> None:
        assert _should_preserve_popup(url)

    def test_account_ubisoft_preserves(self) -> None:
        assert _should_preserve_popup("https://account.ubisoft.com/en-US/login")

    def test_logged_in_merges(self) -> None:
        assert not _should_preserve_popup("https://connect.ubisoft.com/logged-in.html")

    def test_ubisoft_connect_games_merges(self) -> None:
        assert not _should_preserve_popup(
            "https://www.ubisoft.com/en-us/ubisoft-connect/games"
        )


class TestRegisterPageDebugger:
    def test_register_page_skips_debugger_for_storefront_auth(self) -> None:
        ctx = _bare_context()
        ctx._pages_by_session = {}
        ctx._pages_by_target = {}
        calls: list[tuple[str, str | None]] = []

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append((method, session_id))
            return {}

        ctx._send = fake_send  # type: ignore[method-assign]
        ctx._init_scripts = []
        ctx._apply_init_script = lambda page, source: None  # type: ignore[method-assign]

        page = ctx._register_page("TARGET-1", "SESSION-1")

        assert isinstance(page, CdpPage)
        assert not any(m.startswith("Debugger.") for m, _ in calls)
        assert ("Page.enable", "SESSION-1") in calls
        assert ("Network.enable", "SESSION-1") in calls


class TestCdpErrors:
    def test_websocket_403_message(self) -> None:
        err = _cdp_websocket_error(
            Exception("Handshake status 403 Forbidden - remote-allow-origins")
        )
        assert "403" in str(err) or "blocked" in str(err).lower()
        assert "remote-allow-origins" in str(err)
        assert _BROWSER_LAUNCH_HINT in str(err)

    def test_websocket_generic_message(self) -> None:
        err = _cdp_websocket_error(Exception("connection reset"))
        assert "connection reset" in str(err)
        assert _BROWSER_LAUNCH_HINT in str(err)


class TestCookiesRouting:
    def test_uses_page_session_for_network_getallcookies(self) -> None:
        ctx = _bare_context()
        ctx.pages = [_FakePage("SESSION-1")]
        calls: list[tuple[str, str | None]] = []

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append((method, session_id))
            if method == "Network.getAllCookies":
                return {"cookies": [{"name": "MIST", "value": "abc", "domain": "ec.nintendo.com"}]}
            return {}

        ctx._send = fake_send  # type: ignore[method-assign]
        cookies = ctx.cookies()

        assert ("Network.getAllCookies", "SESSION-1") in calls
        assert cookies == [{"name": "MIST", "value": "abc", "domain": "ec.nintendo.com"}]

    def test_falls_back_to_storage_getcookies(self) -> None:
        ctx = _bare_context()
        ctx.pages = [_FakePage("SESSION-1")]
        calls: list[str] = []

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append(method)
            if method == "Network.getAllCookies":
                return {}  # nothing on the page session
            if method == "Storage.getCookies":
                return {"cookies": [{"name": "x", "value": "1", "domain": "gog.com"}]}
            return {}

        ctx._send = fake_send  # type: ignore[method-assign]
        cookies = ctx.cookies()

        assert "Network.getAllCookies" in calls
        assert "Storage.getCookies" in calls
        assert cookies == [{"name": "x", "value": "1", "domain": "gog.com"}]


class TestRunnerCdpCompat:
    """CdpPage.is_closed is a property — calling is_closed() raises bool-not-callable."""

    def test_runner_does_not_call_is_closed_as_method(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner_src = (root / "auth" / "runner.py").read_text(encoding="utf-8")
        assert ".is_closed()" not in runner_src


class TestAuthBanner:
    def test_init_script_embeds_message_and_setter(self) -> None:
        src = auth_banner_init_script('keep "this" window open')
        # Message is JSON-encoded so quotes can't break the script.
        assert '"keep \\"this\\" window open"' in src
        assert "window.__baklogSetBanner" in src
        assert "__baklog_auth_banner" in src
        assert "pointer-events:none" in src

    def test_set_auth_banner_pushes_to_live_pages_only(self) -> None:
        ctx = _bare_context()
        open_page = _FakePage("S-OPEN")
        closed_page = _FakePage("S-CLOSED")
        closed_page.is_closed = True
        evaluated: list[str] = []
        open_page.evaluate = lambda fn, timeout=5: evaluated.append(fn)  # type: ignore[attr-defined]
        closed_page.evaluate = lambda fn, timeout=5: evaluated.append("CLOSED")  # type: ignore[attr-defined]
        ctx.pages = [open_page, closed_page]

        ctx.set_auth_banner("Sign in and keep this window open")

        assert len(evaluated) == 1
        assert "__baklogSetBanner" in evaluated[0]
        assert "Sign in and keep this window open" in evaluated[0]

    def test_set_auth_banner_ignores_blank_message(self) -> None:
        ctx = _bare_context()
        page = _FakePage("S-1")
        page.evaluate = lambda fn, timeout=5: (_ for _ in ()).throw(AssertionError("called"))  # type: ignore[attr-defined]
        ctx.pages = [page]
        ctx.set_auth_banner("")  # no live update for empty text


class TestLaunchArgs:
    def test_off_screen_headed_uses_window_position(self, tmp_path: Path) -> None:
        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"

        class LaunchArgsCaptured(Exception):
            def __init__(self, args: list[str]) -> None:
                self.args = args

        def fake_popen(args, **kwargs):
            raise LaunchArgsCaptured(list(args))

        import auth.cdp_browser as cdp

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(cdp.subprocess, "Popen", fake_popen)
        try:
            with pytest.raises(LaunchArgsCaptured) as exc:
                launch_persistent_profile(
                    profile,
                    headless=False,
                    window_position=(-32000, -32000),
                )
        finally:
            monkeypatch.undo()

        args = exc.value.args
        assert "--window-position=-32000,-32000" in args
        assert "--window-size=1280,900" in args
        assert "--start-maximized" not in args
        assert not any(a.startswith("--headless") for a in args)

    def test_headed_default_uses_start_maximized(self, tmp_path: Path) -> None:
        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"

        class LaunchArgsCaptured(Exception):
            def __init__(self, args: list[str]) -> None:
                self.args = args

        def fake_popen(args, **kwargs):
            raise LaunchArgsCaptured(list(args))

        import auth.cdp_browser as cdp

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(cdp.subprocess, "Popen", fake_popen)
        try:
            with pytest.raises(LaunchArgsCaptured) as exc:
                launch_persistent_profile(profile, headless=False)
        finally:
            monkeypatch.undo()

        assert "--start-maximized" in exc.value.args
        assert not any(a.startswith("--window-position=") for a in exc.value.args)


class TestGracefulClose:
    def test_close_sends_browser_close_before_terminate(self) -> None:
        ctx = _bare_context()
        calls: list[str] = []

        class _FakeProc:
            def __init__(self) -> None:
                self.exited = False
                self.terminated = False

            def poll(self) -> int | None:
                return 0 if self.exited else None

            def wait(self, timeout: float | None = None) -> int:
                self.exited = True
                return 0

            def terminate(self) -> None:
                self.terminated = True
                self.exited = True

            def kill(self) -> None:
                self.exited = True

        class _FakeWs:
            def close(self) -> None:
                return None

        proc = _FakeProc()

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append(method)
            return {}

        ctx._proc = proc  # type: ignore[attr-defined]
        ctx._ws = _FakeWs()  # type: ignore[attr-defined]
        ctx._send = fake_send  # type: ignore[method-assign]

        ctx.close()

        assert calls == ["Browser.close"]
        assert proc.exited
        assert not proc.terminated

    def test_close_sends_browser_close_even_when_proc_already_exited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Launcher proc may exit before the visible window; CDP must still close it."""
        ctx = _bare_context()
        calls: list[str] = []

        class _ExitedProc:
            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                raise AssertionError("should not terminate an already-exited launcher")

            def kill(self) -> None:
                raise AssertionError("should not kill an already-exited launcher")

        class _FakeWs:
            def close(self) -> None:
                return None

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append(method)
            return {}

        monkeypatch.setattr(
            "auth.cdp_browser._pids_listening_on_local_port", lambda _port: []
        )

        ctx._proc = _ExitedProc()  # type: ignore[attr-defined]
        ctx._ws = _FakeWs()  # type: ignore[attr-defined]
        ctx._port = 9222  # type: ignore[attr-defined]
        ctx._send = fake_send  # type: ignore[method-assign]

        ctx.close()

        assert calls == ["Browser.close"]

    def test_close_kills_debug_port_when_proc_already_exited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the launcher proc is gone, force-quit the CDP listener on our port."""
        ctx = _bare_context()
        calls: list[str] = []
        killed: list[int] = []

        class _ExitedProc:
            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                raise AssertionError("should not terminate an already-exited launcher")

            def kill(self) -> None:
                raise AssertionError("should not kill an already-exited launcher")

        class _FakeWs:
            def close(self) -> None:
                return None

        def fake_send(method, params=None, *, session_id=None, timeout=60):
            calls.append(method)
            return {}

        monkeypatch.setattr(
            "auth.cdp_browser._pids_listening_on_local_port", lambda port: [4242]
        )
        monkeypatch.setattr(
            "auth.cdp_browser._kill_pids",
            lambda pids: killed.extend(pids) or list(pids),
        )

        ctx._proc = _ExitedProc()  # type: ignore[attr-defined]
        ctx._ws = _FakeWs()  # type: ignore[attr-defined]
        ctx._port = 9222  # type: ignore[attr-defined]
        ctx._send = fake_send  # type: ignore[method-assign]

        ctx.close()

        assert calls == ["Browser.close"]
        assert killed == [4242]


class TestFindBrowser:
    def test_override_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("BAKLOG_CHROME_PATH", str(exe))
        assert find_chromium_executable() == exe

    def test_missing_override_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BAKLOG_CHROME_PATH", "/no/such/browser.exe")
        with pytest.raises(RuntimeError, match="BAKLOG_CHROME_PATH"):
            find_chromium_executable()

    def test_macos_chrome_candidate(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("BAKLOG_CHROME_PATH", raising=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        chrome = tmp_path / "Google Chrome.app/Contents/MacOS/Google Chrome"
        chrome.parent.mkdir(parents=True)
        chrome.write_bytes(b"")

        def fake_candidates() -> list[Path]:
            return [chrome]

        import auth.cdp_browser as cdp

        monkeypatch.setattr(cdp, "_chromium_executable_candidates", fake_candidates)
        assert str(find_chromium_executable()) == str(chrome)

    def test_linux_which_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("BAKLOG_CHROME_PATH", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        chrome = tmp_path / "google-chrome-stable"
        chrome.write_bytes(b"")

        import auth.cdp_browser as cdp

        monkeypatch.setattr(cdp, "_chromium_executable_candidates", lambda: [])
        monkeypatch.setattr(
            cdp.shutil,
            "which",
            lambda name: str(chrome) if name == "google-chrome-stable" else None,
        )
        assert str(find_chromium_executable()) == str(chrome)

    def test_posix_candidates_include_edge_and_brave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        paths = {p.as_posix() for p in _chromium_executable_candidates()}
        assert "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" in paths
        assert "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" in paths
        assert "/opt/google/chrome/chrome" in paths


@pytest.mark.integration
def test_launch_goto_title() -> None:
    """Smoke-test CDP launch when a system browser is available."""
    if os.getenv("BAKLOG_SKIP_CDP_INTEGRATION"):
        pytest.skip("BAKLOG_SKIP_CDP_INTEGRATION set")
    try:
        find_chromium_executable()
    except RuntimeError:
        pytest.skip("No Chrome or Edge installed")

    profile = Path(tempfile.mkdtemp(prefix="baklog-cdp-test-"))
    try:
        with launch_persistent_profile(profile, headless=True) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://example.com", wait_until="domcontentloaded", timeout=30_000)
            title = page.title()
            assert "Example" in title
    finally:
        import shutil

        shutil.rmtree(profile, ignore_errors=True)
