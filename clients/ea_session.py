"""EA web-session Bearer capture, probe, and login-page detection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .ea_client import EaAuthError, EaCaptureError, EaClient

EA_GRAPHQL_HOST = "service-aggregation-layer.juno.ea.com"
EA_LOGIN_URL = "https://www.ea.com/login"
EA_DEALS_URL = "https://www.ea.com/sales/deals"
EA_HOME_URL = "https://www.ea.com/"
DEFAULT_TRIGGER_URLS = (EA_DEALS_URL, EA_HOME_URL)


def normalize_bearer(auth: str | None) -> str | None:
    if not auth or not str(auth).strip():
        return None
    token = str(auth).strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def is_ea_login_page(html: str, url: str) -> bool:
    u = (url or "").lower()
    if "signin.ea.com" in u or "/login" in u:
        return True
    lower = (html or "")[:8000].lower()
    if "sign in" in lower and "ea account" in lower:
        return True
    if "log in" in lower and "electronic arts" in lower:
        return True
    return False


def probe_ea_token(token: str, cookies: list[dict] | dict | None = None) -> dict[str, Any]:
    """Lightweight GraphQL probe; returns {ok, error}."""
    out: dict[str, Any] = {"ok": False, "error": None}
    if not (token or "").strip():
        out["error"] = "empty token"
        return out
    try:
        EaClient(token, cookies=cookies).probe_owned_games()
        out["ok"] = True
        return out
    except EaAuthError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        return out


@dataclass
class SniffResult:
    token: str
    cookies: list[dict]
    debug: dict[str, Any] = field(default_factory=dict)


def sniff_ea_bearer(
    ctx: Any,
    page: Any,
    *,
    trigger_urls: tuple[str, ...] = DEFAULT_TRIGGER_URLS,
    timeout_s: int = 45,
    debug_out: dict[str, Any] | None = None,
) -> SniffResult:
    """Open trigger pages and capture Juno GraphQL Bearer from request headers."""
    captured: dict[str, str] = {}
    stats: dict[str, Any] = debug_out if debug_out is not None else {}
    stats.setdefault("graphql_requests_seen", 0)
    stats.setdefault("token_captured", False)
    stats["trigger_urls"] = list(trigger_urls)

    def on_request(request: Any) -> None:
        url = getattr(request, "url", None) or ""
        if EA_GRAPHQL_HOST not in url.lower():
            return
        stats["graphql_requests_seen"] = int(stats["graphql_requests_seen"]) + 1
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = normalize_bearer(auth)
        if token:
            captured["token"] = token

    ctx.on("request", on_request)
    deadline = time.time() + timeout_s
    for trigger in trigger_urls:
        if captured.get("token"):
            break
        try:
            page.goto(trigger, wait_until="domcontentloaded", timeout=min(25, timeout_s) * 1000)
        except Exception:  # noqa: BLE001
            pass
        while time.time() < deadline and "token" not in captured:
            page.wait_for_timeout(500)

    stats["final_url"] = getattr(page, "url", None) or ""
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        html = ""
    stats["login_page"] = is_ea_login_page(html, stats["final_url"])

    token = captured.get("token") or ""
    cookies = ctx.cookies()
    stats["token_captured"] = bool(token)

    if not token:
        if stats["login_page"]:
            raise EaAuthError(
                "EA sign-in required — open Connections → EA App → Reconnect and sign in at ea.com."
            )
        raise EaCaptureError(
            "Could not capture an EA web-session token from the saved profile. "
            "Try: python fetch_ea.py --skip-hltb --headed --dump-debug "
            "(inspect cache/ea/fetch_debug.json)."
        )

    return SniffResult(token=token, cookies=cookies, debug=stats)
