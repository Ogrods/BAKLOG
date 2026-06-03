"""Unit tests for CDP browser helpers; optional integration if Chrome/Edge exists.

Integration smoke test (requires Chrome or Edge installed locally):

    pytest tests/test_cdp_browser.py -m integration

Skip integration explicitly:

    BAKLOG_SKIP_CDP_INTEGRATION=1 pytest tests/test_cdp_browser.py -m integration

GitHub Actions: run the manual "CDP smoke" workflow after a suspected browser regression.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from auth.cdp_browser import (
    _BROWSER_LAUNCH_HINT,
    CdpContext,
    _cdp_websocket_error,
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
