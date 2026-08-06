"""PSN connect helpers — stale cookie must not block ssocookie API."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from auth.connect_loop import run_connect_poll
from auth.runner import _fetch_npsso_background


def test_ssocookie_api_used_when_cookie_jar_empty() -> None:
    page = MagicMock()
    page.evaluate.return_value = "fresh-from-ssocookie-token-value"
    context = MagicMock()
    context.cookies.return_value = []

    token, source = _fetch_npsso_background(page, context)
    assert source == "ssocookie"
    assert token == "fresh-from-ssocookie-token-value"


def test_ssocookie_api_preferred_over_stale_cookie_jar() -> None:
    page = MagicMock()
    page.evaluate.return_value = "fresh-from-ssocookie"
    context = MagicMock()
    context.cookies.return_value = [{"name": "npsso", "value": "stale-jar-token"}]

    token, source = _fetch_npsso_background(page, context)
    assert source == "ssocookie"
    assert token == "fresh-from-ssocookie"


def test_cookie_jar_used_when_ssocookie_empty() -> None:
    page = MagicMock()
    page.evaluate.return_value = ""
    context = MagicMock()
    context.cookies.return_value = [{"name": "npsso", "value": "jar-only-token"}]

    token, source = _fetch_npsso_background(page, context)
    assert source == "cookie"
    assert token == "jar-only-token"


def test_psn_run_connect_poll_survives_check_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exceptions should not kill the browser session (Battle.net parity)."""
    monkeypatch.setattr(
        "auth.connect_loop.abort_if_browser_closed",
        lambda _context: None,
    )
    context = MagicMock()
    context.pages = []
    calls = {"n": 0}

    def _check():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient DOM glitch")
        return {"PSN_NPSSO": "ok-token"}

    creds = run_connect_poll(
        context=context,
        session=None,
        deadline=time.time() + 5,
        poll_sec=0.01,
        check=_check,
        timeout_message="timeout",
    )
    assert creds == {"PSN_NPSSO": "ok-token"}
    assert calls["n"] >= 2
