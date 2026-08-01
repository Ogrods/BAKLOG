"""Unit tests for CDP browser helpers; optional integration if Chrome/Edge exists.

Integration smoke test (requires Chrome or Edge installed locally):

    pytest tests/test_cdp_browser.py -m integration

Skip integration explicitly:

    BAKLOG_SKIP_CDP_INTEGRATION=1 pytest tests/test_cdp_browser.py -m integration

GitHub Actions: run the manual "CDP smoke" workflow after a suspected browser regression.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import urllib.error
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


class TestNetworkExtraInfo:
    def test_extra_info_merges_authorization_and_redispatches(self) -> None:
        ctx = _bare_context()
        ctx._request_handlers = []
        page = CdpPage(ctx, "TARGET-1", "SESSION-1")
        seen: list[bool] = []

        def handler(req) -> None:
            auth = req.headers.get("authorization")
            seen.append(bool(auth))

        ctx._request_handlers.append(handler)

        page._handle_network_event(
            "Network.requestWillBeSent",
            {
                "requestId": "req-1",
                "request": {
                    "url": "https://service-aggregation-layer.juno.ea.com/graphql",
                    "headers": {"accept": "application/json"},
                },
            },
        )
        assert seen == [False]

        page._handle_network_event(
            "Network.requestWillBeSentExtraInfo",
            {
                "requestId": "req-1",
                "headers": {"Authorization": "Bearer ea-test-token"},
            },
        )
        assert seen == [False, True]
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


class TestHttpClient:
    def test_post_forwards_cookies_and_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import auth.cdp_browser as cdp

        ctx = _bare_context()
        ctx.cookies = lambda: [{"name": "remid", "value": "abc", "domain": ".ea.com"}]  # type: ignore[method-assign]
        captured: dict = {}

        class _FakeResp:
            status_code = 200
            text = '{"ok":true}'

        def fake_post(url, *, cookies, headers, data, json, timeout):
            captured.update(
                {"url": url, "cookies": cookies, "headers": headers, "data": data, "json": json}
            )
            return _FakeResp()

        monkeypatch.setattr(cdp.requests, "post", fake_post)
        client = cdp.CdpHttpClient(ctx)
        resp = client.post(
            "https://example.com/gql",
            headers={"accept": "application/json"},
            data='{"q":1}',
        )

        assert captured["url"] == "https://example.com/gql"
        assert captured["cookies"] == {"remid": "abc"}
        assert captured["data"] == '{"q":1}'
        assert resp.status == 200
        assert resp.json() == {"ok": True}

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

    def test_headed_launch_disables_extensions(self, tmp_path: Path) -> None:
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

        assert "--disable-extensions" in exc.value.args

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


class TestProfileLockRelease:
    def test_release_chromium_profile_lock_kills_matching_pids(self, monkeypatch, tmp_path: Path) -> None:
        import auth.cdp_browser as cdp

        profile = tmp_path / "ea-profile"
        profile.mkdir()
        killed: list[int] = []

        monkeypatch.setattr(cdp, "pids_holding_chromium_profile", lambda _p: [4242, 5151])
        monkeypatch.setattr(cdp, "_kill_pids", lambda pids, **kwargs: killed.extend(pids) or pids)
        monkeypatch.setattr(cdp.time, "sleep", lambda _s: None)

        out = cdp.release_chromium_profile_lock(profile)
        assert out == [4242, 5151]
        assert killed == [4242, 5151]

    def test_close_browser_bounded_force_releases_when_close_hangs(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        import auth.cdp_browser as cdp

        profile = tmp_path / "xbox-profile"
        profile.mkdir()
        released: list[Path] = []

        class HangCtx:
            def close(self) -> None:
                time.sleep(5.0)

        monkeypatch.setattr(
            cdp,
            "pids_holding_chromium_profile",
            lambda _p: [999] if not released else [],
        )
        monkeypatch.setattr(
            cdp,
            "release_chromium_profile_lock",
            lambda p, wait_sec=3.0: released.append(Path(p)) or [999],
        )

        cdp.close_browser_bounded(HangCtx(), profile=profile, join_timeout=0.05)
        assert released == [profile]


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


class TestLaunchWaitExitZero:
    """Windows Chrome launcher often exits 0 before CDP attaches."""

    @staticmethod
    def _popen_only_fake(fake_proc_cls, real_popen):
        """Return Popen stand-in that fakes Chrome launches only.

        Patching ``subprocess.Popen`` globally breaks conftest leak detection
        (tasklist/ps), so non-Chrome calls must use the real Popen.
        """

        def _popen(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            first = str(cmd[0]) if cmd else ""
            if first.endswith("chrome.exe") or first.endswith("chrome"):
                return fake_proc_cls()
            return real_popen(*args, **kwargs)

        return _popen

    def test_exit_zero_waits_for_cdp_then_attaches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import auth.cdp_browser as cdp

        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"
        version_hits = {"n": 0}
        real_popen = cdp.subprocess.Popen

        class FakeProc:
            stdout = io.BytesIO(b"")

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                return None

            def communicate(self, input=None, timeout=None):  # noqa: A002
                return (b"", b"")

            def __enter__(self) -> FakeProc:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        class FakeWs:
            def recv(self) -> str:
                raise ConnectionError("closed")

            def close(self) -> None:
                return None

            def send(self, _data: str) -> None:
                return None

        def fake_fetch(url: str, timeout: float = 2) -> dict | list:
            if "/json/version" in url:
                version_hits["n"] += 1
                if version_hits["n"] < 2:
                    raise urllib.error.URLError("not ready")
                return {
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/x"
                }
            if "/json/list" in url:
                return [{"type": "page", "id": "T1", "url": "about:blank"}]
            return {}

        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(
            cdp.subprocess,
            "Popen",
            self._popen_only_fake(FakeProc, real_popen),
        )
        monkeypatch.setattr(cdp, "_fetch_json", fake_fetch)
        monkeypatch.setattr(cdp.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            cdp.websocket, "create_connection", lambda *a, **k: FakeWs()
        )
        monkeypatch.setattr(
            cdp.CdpContext,
            "_send",
            lambda self, method, params=None, timeout=60: {"result": {}},
        )
        monkeypatch.setattr(
            cdp.CdpContext,
            "_attach_page",
            lambda self, target_id: _FakePage(f"S-{target_id}"),
        )
        monkeypatch.setattr(cdp.CdpContext, "add_init_script", lambda self, _s: None)

        ctx = launch_persistent_profile(profile, headless=False)
        assert version_hits["n"] >= 2
        assert len(ctx.pages) == 1
        ctx.close = lambda: None  # type: ignore[method-assign]

    def test_exit_zero_without_cdp_times_out(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import auth.cdp_browser as cdp

        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"
        kill_calls: list[list[int]] = []
        clock = {"t": 0.0}
        real_popen = cdp.subprocess.Popen

        class FakeProc:
            stdout = io.BytesIO(b"")

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                return None

            def communicate(self, input=None, timeout=None):  # noqa: A002
                return (b"", b"")

            def __enter__(self) -> FakeProc:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_fetch(url: str, timeout: float = 2) -> dict:
            raise urllib.error.URLError("never")

        def fake_sleep(_s: float) -> None:
            # Jump past the 30s CDP wait so each attempt ends quickly.
            clock["t"] += 40.0

        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(
            cdp.subprocess,
            "Popen",
            self._popen_only_fake(FakeProc, real_popen),
        )
        monkeypatch.setattr(cdp, "_fetch_json", fake_fetch)
        monkeypatch.setattr(cdp.time, "sleep", fake_sleep)
        monkeypatch.setattr(cdp.time, "time", lambda: clock["t"])
        monkeypatch.setattr(cdp, "pids_holding_chromium_profile", lambda _p: [])
        monkeypatch.setattr(cdp, "_pids_listening_on_local_port", lambda _p: [])
        monkeypatch.setattr(
            cdp,
            "_kill_pids",
            lambda pids, wait_sec=3.0: kill_calls.append(list(pids)) or [],
        )
        lock_calls: list[Path] = []
        monkeypatch.setattr(
            cdp,
            "release_chromium_profile_lock",
            lambda p, wait_sec=3.0: lock_calls.append(Path(p)) or [],
        )

        with pytest.raises(RuntimeError, match="did not start CDP"):
            launch_persistent_profile(profile, headless=False)
        # No pre-existing holders: extend wait + relaunch, never blanket-kill
        # the profile (that closed the Connect window under the user).
        assert lock_calls == []

    def test_exit_zero_kills_only_pre_existing_holders(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import auth.cdp_browser as cdp

        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"
        kill_calls: list[list[int]] = []
        clock = {"t": 0.0}
        real_popen = cdp.subprocess.Popen
        holders = {"pids": [4242]}

        class FakeProc:
            stdout = io.BytesIO(b"")

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                return None

            def communicate(self, input=None, timeout=None):  # noqa: A002
                return (b"", b"")

            def __enter__(self) -> FakeProc:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_fetch(url: str, timeout: float = 2) -> dict:
            raise urllib.error.URLError("never")

        def fake_sleep(_s: float) -> None:
            clock["t"] += 40.0

        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(
            cdp.subprocess,
            "Popen",
            self._popen_only_fake(FakeProc, real_popen),
        )
        monkeypatch.setattr(cdp, "_fetch_json", fake_fetch)
        monkeypatch.setattr(cdp.time, "sleep", fake_sleep)
        monkeypatch.setattr(cdp.time, "time", lambda: clock["t"])
        monkeypatch.setattr(
            cdp,
            "pids_holding_chromium_profile",
            lambda _p: list(holders["pids"]),
        )
        monkeypatch.setattr(cdp, "_pids_listening_on_local_port", lambda _p: [])
        monkeypatch.setattr(
            cdp,
            "_kill_pids",
            lambda pids, wait_sec=3.0: kill_calls.append(list(pids)) or holders.update(pids=[]) or [],
        )

        with pytest.raises(RuntimeError, match="did not start CDP"):
            launch_persistent_profile(profile, headless=False)
        assert any(4242 in call for call in kill_calls)

    def test_nonzero_exit_still_raises_immediately(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import auth.cdp_browser as cdp

        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        profile = tmp_path / "profile"
        real_popen = cdp.subprocess.Popen

        class FakeProc:
            stdout = io.BytesIO(b"boom")

            def poll(self) -> int:
                return 1

            def kill(self) -> None:
                return None

            def communicate(self, input=None, timeout=None):  # noqa: A002
                return (b"boom", b"")

            def __enter__(self) -> FakeProc:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        monkeypatch.setattr(cdp, "find_chromium_executable", lambda: exe)
        monkeypatch.setattr(cdp, "_free_port", lambda: 9222)
        monkeypatch.setattr(
            cdp.subprocess,
            "Popen",
            self._popen_only_fake(FakeProc, real_popen),
        )
        monkeypatch.setattr(cdp.time, "sleep", lambda _s: None)
        monkeypatch.setattr(
            cdp,
            "_fetch_json",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")),
        )

        with pytest.raises(RuntimeError, match="exited immediately \\(code 1\\)"):
            launch_persistent_profile(profile, headless=False)


class TestBrowserSessionGone:
    def test_exited_launcher_proc_is_not_gone_when_socket_live(self) -> None:
        from auth.cdp_browser import browser_session_gone

        class _Proc:
            def poll(self) -> int:
                return 0

        class _Ctx:
            _ws_dead = False
            _proc = _Proc()
            pages = []

        assert browser_session_gone(_Ctx()) is False

    def test_detects_all_pages_closed(self) -> None:
        from auth.cdp_browser import (
            ConnectBrowserClosed,
            abort_if_browser_closed,
            browser_session_gone,
        )

        class _Page:
            _closed = True

            @property
            def is_closed(self) -> bool:
                return self._closed

        class _Proc:
            def poll(self) -> None:
                return None

        class _Ctx:
            _ws_dead = False
            _proc = _Proc()
            pages = [_Page()]

        assert browser_session_gone(_Ctx()) is True
        with pytest.raises(ConnectBrowserClosed):
            abort_if_browser_closed(_Ctx())

    def test_live_browser_not_gone(self) -> None:
        from auth.cdp_browser import browser_session_gone

        class _Page:
            @property
            def is_closed(self) -> bool:
                return False

        class _Proc:
            def poll(self) -> None:
                return None

        class _Ctx:
            _ws_dead = False
            _proc = _Proc()
            pages = [_Page()]

        assert browser_session_gone(_Ctx()) is False
