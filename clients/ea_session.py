"""EA web-session Bearer capture, probe, and login-page detection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ea_client import (
    EA_PLAY_OWNERSHIP,
    EA_WEB_ORIGIN,
    EA_WEB_REFERER,
    EaAuthError,
    EaCaptureError,
    EaClient,
    GRAPHQL_URL,
    OWNED_GAMES_HASH,
    REAL_OWNERSHIP,
    XGP_ONLY,
    owned_games_full_document_body,
)

EA_COOKIE_SESSION = "cookie"

EA_GQL_FETCH_HOOK = """
(() => {
  if (window.__baklogEaGqlReady) return;
  window.__baklogEaGqlReady = true;
  window.__baklogEaGql = [];
  const host = "service-aggregation-layer.juno.ea.com";
  const push = (url, status, text) => {
    try {
      window.__baklogEaGql.push({
        url: String(url || ""),
        status: Number(status) || 0,
        text: String(text || "").slice(0, 500000),
      });
    } catch (e) {}
  };
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await origFetch.apply(this, args);
    try {
      const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url) || "";
      if (url.includes(host)) {
        push(url, res.status, await res.clone().text());
      }
    } catch (e) {}
    return res;
  };
  const OrigXHR = window.XMLHttpRequest;
  function HookXHR() {
    const xhr = new OrigXHR();
    const open = xhr.open;
    xhr.open = function (method, url, ...rest) {
      xhr.__baklogUrl = url;
      return open.call(xhr, method, url, ...rest);
    };
    xhr.addEventListener("load", function () {
      try {
        if (String(xhr.__baklogUrl || "").includes(host)) {
          push(xhr.__baklogUrl, xhr.status, xhr.responseText || "");
        }
      } catch (e) {}
    });
    return xhr;
  }
  window.XMLHttpRequest = HookXHR;
})();
"""


EA_GRAPHQL_HOST = "service-aggregation-layer.juno.ea.com"
EA_LOGIN_URL = "https://www.ea.com/login"
EA_DEALS_URL = "https://www.ea.com/sales/deals"
EA_HOME_URL = "https://www.ea.com/"
EA_LIBRARY_URLS = (
    EA_DEALS_URL,
    EA_HOME_URL,
    "https://www.ea.com/games",
    "https://www.ea.com/ea-app",
)
DEFAULT_TRIGGER_URLS = (EA_DEALS_URL, EA_HOME_URL)
COOKIE_PROBE_INTERVAL_SEC = 3.0
EA_SESSION_COOKIE = "remid"
CONNECT_SNAPSHOT_TTL_SEC = 600


def ea_connect_snapshot_path() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "ea" / "connect_snapshot.json"


def write_ea_connect_snapshot(
    owned_items: list[dict],
    *,
    browser_auth_ok: bool = True,
    cookies: list[dict] | None = None,
) -> Path:
    """Persist hook-owned rows from Connect for fetch handoff without a second browser."""
    path = ea_connect_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "owned_items": owned_items,
        "browser_auth_ok": browser_auth_ok,
    }
    if cookies:
        payload["cookies"] = [
            {
                "name": c.get("name"),
                "value": c.get("value"),
                "domain": c.get("domain"),
                "path": c.get("path") or "/",
            }
            for c in cookies
            if isinstance(c, dict) and c.get("name") and c.get("value") is not None
        ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_ea_connect_snapshot(*, max_age_sec: int = CONNECT_SNAPSHOT_TTL_SEC) -> dict[str, Any] | None:
    """Return a fresh connect snapshot after a headed Connect (auth ok; owned rows optional)."""
    path = ea_connect_snapshot_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("browser_auth_ok"):
        return None
    items = data.get("owned_items") or []
    if not isinstance(items, list):
        return None
    captured_at = data.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        return None
    try:
        ts = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - ts).total_seconds()
        if age > max_age_sec:
            return None
    except (TypeError, ValueError):
        return None
    return data


def launch_ea_profile(profile_path: str | Path, *, visible: bool = False) -> Any:
    """Open the saved EA browser profile for fetch/capture.

    EA's Juno SPA only fires GraphQL in a normal headed window (not headless,
    minimized, or off-screen). Dashboard fetch briefly opens that window.
    """
    from auth.cdp_browser import launch_persistent_profile, release_chromium_profile_lock
    from auth.manager import has_active_sessions

    _ = visible  # --headed and dashboard both need the same real window fingerprint.
    if not has_active_sessions():
        release_chromium_profile_lock(profile_path)
    return launch_persistent_profile(str(profile_path), headless=False)


def install_ea_graphql_hook(context: Any) -> None:
    """Install in-page fetch/XHR capture before navigating ea.com pages."""
    add = getattr(context, "add_init_script", None)
    if callable(add):
        add(EA_GQL_FETCH_HOOK)


def ensure_ea_graphql_hook(page: Any) -> None:
    """Best-effort hook on the current document (init script may have missed)."""
    try:
        page.evaluate(EA_GQL_FETCH_HOOK)
    except Exception:  # noqa: BLE001
        pass


def read_captured_ea_graphql(page: Any) -> list[dict[str, Any]]:
    """Drain hook-captured Juno GraphQL payloads from the live page."""
    try:
        raw = page.evaluate(
            "() => { const q = window.__baklogEaGql || []; window.__baklogEaGql = []; return q; }"
        )
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        try:
            payload = json.loads(entry.get("text") or "")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(payload, dict):
            out.append(
                {
                    "status": entry.get("status"),
                    "url": entry.get("url"),
                    "payload": payload,
                }
            )
    return out


def ea_graphql_authenticated(payload: dict[str, Any]) -> bool:
    if payload.get("errors"):
        err = payload["errors"][0] if payload["errors"] else {}
        code = ((err.get("extensions") or {}).get("code") or "").upper()
        msg = str(err.get("message") or "").lower()
        if code == "UNAUTHENTICATED" or "not authenticated" in msg:
            return False
    me = (payload.get("data") or {}).get("me")
    if not isinstance(me, dict) or not me:
        return False
    if me.get("ownedGameProducts") is not None:
        return True
    for key in (
        "subscription",
        "activeSubscription",
        "subscriber",
        "userSubscription",
        "entitlements",
    ):
        if key in me:
            return True
    if me.get("id") or me.get("pidId"):
        return True
    return False


def ea_graphql_owned_items(payload: dict[str, Any]) -> list[dict]:
    owned = ((payload.get("data") or {}).get("me") or {}).get("ownedGameProducts") or {}
    items = owned.get("items") or []
    return [i for i in items if isinstance(i, dict)]


def drain_ea_graphql_hook(page: Any) -> tuple[bool, list[dict], dict[str, Any]]:
    """Return (authenticated, owned_items, stats) from hook-captured traffic."""
    stats: dict[str, Any] = {
        "hook_entries": 0,
        "hook_authenticated": False,
        "hook_owned_items": 0,
        "hook_unauthenticated": False,
    }
    owned: list[dict] = []
    authenticated = False
    for entry in read_captured_ea_graphql(page):
        stats["hook_entries"] = int(stats["hook_entries"]) + 1
        payload = entry.get("payload") or {}
        if ea_graphql_authenticated(payload):
            authenticated = True
            stats["hook_authenticated"] = True
        elif payload.get("errors"):
            err = payload["errors"][0] if payload["errors"] else {}
            msg = str(err.get("message") or "").lower()
            if "not authenticated" in msg:
                stats["hook_unauthenticated"] = True
        batch = ea_graphql_owned_items(payload)
        if batch:
            owned.extend(batch)
            stats["hook_owned_items"] = len(owned)
    return authenticated, owned, stats


def _owned_apq_page_variables(*, limit: int, offset: str) -> dict[str, Any]:
    return {
        "isMac": False,
        "locale": "DEFAULT",
        "type": ["DIGITAL_FULL_GAME", "PACKAGED_FULL_GAME"],
        "entitlementEnabled": True,
        "storefronts": ["EA"],
        "ownershipMethods": sorted(REAL_OWNERSHIP | EA_PLAY_OWNERSHIP | XGP_ONLY),
        "platforms": ["PC"],
        "addFieldsToPreloadGames": True,
        "limit": limit,
        "next": offset,
    }


_INPAGE_OWNED_EVAL = """
async ({ url, body }) => {
  try {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      referrer: 'https://www.ea.com/sales/deals',
      referrerPolicy: 'strict-origin-when-cross-origin',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        'x-client-id': 'eacom-fe',
      },
      body: JSON.stringify(body),
    });
    const text = await r.text();
    let payload = null;
    try {
      payload = JSON.parse(text);
    } catch (e) {}
    return { status: r.status, payload, text: payload ? null : text.slice(0, 400) };
  } catch (e) {
    return { status: 0, error: String(e) };
  }
}
"""


def _owned_graphql_should_fallback(message: str) -> bool:
    msg = (message or "").lower()
    return "persistedquerynotfound" in msg or "graphql validation error" in msg


def _inpage_owned_eval(page: Any, *, body: dict[str, Any]) -> Any:
    """Run owned-games GraphQL POST in-page; CdpPage.evaluate accepts one expression only."""
    args = {"url": GRAPHQL_URL, "body": body}
    return page.evaluate(
        f"""async () => {{
          const fn = {_INPAGE_OWNED_EVAL};
          return await fn({json.dumps(args)});
        }}"""
    )



def _ensure_ea_deals_ready(page: Any, *, dwell_ms: int = 2500) -> None:
    """Navigate to the deals SPA and wait before in-page Juno fetch."""
    url = (getattr(page, "url", None) or "").lower()
    if "ea.com/sales/deals" not in url:
        try:
            page.goto(EA_DEALS_URL, wait_until="load", timeout=30_000)
        except Exception:  # noqa: BLE001
            pass
    ensure_ea_graphql_hook(page)
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:  # noqa: BLE001
        pass


def fetch_owned_games_playwright_request(
    context: Any,
    *,
    page_size: int = 500,
    max_pages: int = 20,
) -> list[dict]:
    """Paginate owned games via Playwright APIRequestContext (browser cookie jar)."""
    request = getattr(context, "request", None)
    if request is None:
        return []
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "x-client-id": "eacom-fe",
        "Origin": EA_WEB_ORIGIN,
        "Referer": EA_DEALS_URL,
    }
    out: list[dict] = []
    seen: set[str] = set()
    offset = "0"
    use_full_document = False
    for page_idx in range(max_pages):
        if use_full_document:
            body = owned_games_full_document_body(limit=page_size, offset=offset)
        else:
            variables = _owned_apq_page_variables(limit=page_size, offset=offset)
            body = {
                "operationName": "getPreloadedOwnedGames",
                "variables": variables,
                "extensions": {
                    "persistedQuery": {"version": 1, "sha256Hash": OWNED_GAMES_HASH},
                },
            }
        try:
            resp = request.post(GRAPHQL_URL, headers=headers, data=json.dumps(body))
            status = int(getattr(resp, "status", 0) or 0)
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            break
        errors = payload.get("errors") or []
        if errors:
            err = errors[0] if isinstance(errors[0], dict) else {}
            msg = str(err.get("message") or "")
            if out:
                return out
            if "not authenticated" in msg.lower():
                raise EaAuthError("EA GraphQL not authenticated — reconnect EA App.")
            if not use_full_document and _owned_graphql_should_fallback(msg):
                use_full_document = True
                continue
            break
        batch = ea_graphql_owned_items(payload)
        _merge_owned_items(out, seen, batch)
        next_offset = (
            ((payload.get("data") or {}).get("me") or {}).get("ownedGameProducts") or {}
        ).get("next")
        if not next_offset:
            break
        offset = str(next_offset)
    return out


def fetch_owned_games_inpage(page: Any, *, page_size: int = 500, max_pages: int = 20) -> list[dict]:
    """Paginate owned games via in-page Juno POST (browser-bound auth)."""
    out: list[dict] = []
    seen: set[str] = set()
    offset = "0"
    use_full_document = False
    for page_idx in range(max_pages):
        if use_full_document:
            body = owned_games_full_document_body(limit=page_size, offset=offset)
        else:
            variables = _owned_apq_page_variables(limit=page_size, offset=offset)
            body = {
                "operationName": "getPreloadedOwnedGames",
                "variables": variables,
                "extensions": {
                    "persistedQuery": {"version": 1, "sha256Hash": OWNED_GAMES_HASH},
                },
            }
        try:
            result = _inpage_owned_eval(page, body=body)
        except Exception as exc:  # noqa: BLE001
            break
        if not isinstance(result, dict):
            break
        status = int(result.get("status") or 0)
        payload = result.get("payload")
        if not isinstance(payload, dict):
            err_text = str(result.get("text") or result.get("error") or "")
            if out and ("failed to fetch" in err_text.lower() or status == 0):
                return out
            if (
                not use_full_document
                and not out
                and (status == 0 or "failed to fetch" in err_text.lower())
            ):
                use_full_document = True
                continue
            break
        errors = payload.get("errors") or []
        if errors:
            err = errors[0] if isinstance(errors[0], dict) else {}
            msg = str(err.get("message") or "")
            if out:
                return out
            if "not authenticated" in msg.lower():
                raise EaAuthError("EA GraphQL not authenticated — reconnect EA App.")
            if not use_full_document and _owned_graphql_should_fallback(msg):
                use_full_document = True
                continue
            break
        batch = ea_graphql_owned_items(payload)
        _merge_owned_items(out, seen, batch)
        next_offset = (
            ((payload.get("data") or {}).get("me") or {}).get("ownedGameProducts") or {}
        ).get("next")
        if not next_offset:
            break
        offset = str(next_offset)
    return out


def has_ea_session_cookie(cookies: list[dict] | dict | None) -> bool:
    if isinstance(cookies, dict):
        return EA_SESSION_COOKIE in cookies
    names = {c.get("name") for c in cookies or [] if c.get("name")}
    return EA_SESSION_COOKIE in names


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


def is_ea_session_expired_page(html: str, url: str) -> bool:
    lower = (html or "")[:12000].lower()
    if "session expired" in lower or "your session has expired" in lower:
        return True
    if "sign in again" in lower and "ea account" in lower:
        return True
    return False


def probe_ea_cookies(cookies: list[dict] | dict | None) -> dict[str, Any]:
    """Verify ea.com session cookies against Juno GraphQL (requests replay).

    EA binds Juno auth to the browser TLS/cookie jar; this often 401s outside
    CDP even when the headed profile is signed in. Prefer drain_ea_graphql_hook.
    """
    out: dict[str, Any] = {"ok": False, "error": None}
    if not cookies:
        out["error"] = "empty cookies"
        return out
    try:
        client = EaClient(cookies=cookies)
        client.probe_user_subscription()
        out["ok"] = True
        return out
    except EaAuthError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        return out


def probe_ea_token(token: str, cookies: list[dict] | dict | None = None) -> dict[str, Any]:
    """Lightweight GraphQL probe; returns {ok, error}."""
    out: dict[str, Any] = {"ok": False, "error": None}
    if not (token or "").strip():
        out["error"] = "empty token"
        return out
    if token.strip() == EA_COOKIE_SESSION:
        out["error"] = "cookie session requires browser GraphQL validation"
        return out
    try:
        client = EaClient(token, cookies=cookies)
        if client._cookie_mode:
            client.probe_user_subscription()
            out["ok"] = True
            return out
        try:
            client.probe_owned_games()
            out["ok"] = True
            return out
        except EaAuthError as exc:
            msg = str(exc)
            if "PersistedQueryNotFound" not in msg:
                out["error"] = msg
                return out
            client.probe_user_subscription()
            out["ok"] = True
            out["library_via_browser"] = True
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
    owned_items: list[dict] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


def _merge_owned_items(out: list[dict], seen: set[str], batch: list[dict]) -> None:
    for item in batch:
        if not isinstance(item, dict):
            continue
        key = str(item.get("originOfferId") or item.get("id") or "")
        if key and key not in seen:
            seen.add(key)
            out.append(item)


def _ea_session_failure(
    stats: dict[str, Any],
    cookies: list[dict],
    *,
    token: str = "",
) -> None:
    """Raise the most accurate EA session error from sniff/capture stats."""
    if stats.get("login_page"):
        raise EaAuthError(
            "EA sign-in required — open Connections → EA App → Reconnect and sign in at ea.com."
        )
    if (
        stats.get("session_expired_page")
        or stats.get("hook_unauthenticated")
        or (
            has_ea_session_cookie(cookies)
            and int(stats.get("graphql_requests_seen") or 0) > 0
            and not token
        )
        or (
            has_ea_session_cookie(cookies)
            and int(stats.get("graphql_requests_seen") or 0) == 0
            and not stats.get("browser_auth_ok")
        )
    ):
        raise EaAuthError(
            "EA session expired — open Connections → EA App → Reconnect and sign in at ea.com."
        )
    raise EaCaptureError(
        "Could not capture an EA web-session token from the saved profile. "
        "Try: python fetch_ea.py --skip-hltb --headed --dump-debug "
        "(inspect cache/ea/fetch_debug.json)."
    )


def capture_ea_browser_session(
    ctx: Any,
    page: Any,
    *,
    timeout_s: int = 45,
    debug_out: dict[str, Any] | None = None,
) -> SniffResult:
    """Confirm a cookie-backed EA session in-page and capture owned hook rows."""
    stats: dict[str, Any] = debug_out if debug_out is not None else {}
    stats.setdefault("graphql_requests_seen", 0)
    stats.setdefault("browser_auth_ok", False)
    stats.setdefault("hook_unauthenticated", False)
    stats.setdefault("token_captured", False)
    stats.setdefault("owned_hook_items", 0)
    stats["token_source"] = "cookie_session"
    stats["trigger_urls"] = [EA_DEALS_URL, EA_HOME_URL]
    owned_items: list[dict] = []
    owned_seen: set[str] = set()

    install_ea_graphql_hook(ctx)
    ensure_ea_graphql_hook(page)

    def on_request(request: Any) -> None:
        url = getattr(request, "url", None) or ""
        if EA_GRAPHQL_HOST not in url.lower():
            return
        stats["graphql_requests_seen"] = int(stats["graphql_requests_seen"]) + 1

    def on_response(response: Any) -> None:
        try:
            url = getattr(response, "url", None) or ""
            if EA_GRAPHQL_HOST not in url.lower():
                return
            if int(getattr(response, "status", 0) or 0) != 200:
                return
            payload = response.json()
            if not isinstance(payload, dict):
                return
            batch = ea_graphql_owned_items(payload)
            if batch:
                _merge_owned_items(owned_items, owned_seen, batch)
                stats["owned_hook_items"] = len(owned_items)
            if ea_graphql_authenticated(payload):
                stats["browser_auth_ok"] = True
        except Exception:  # noqa: BLE001
            pass

    ctx.on("request", on_request)
    ctx.on("response", on_response)

    deadline = time.time() + timeout_s
    min_dwell_deadline = time.time() + min(20, max(10, timeout_s // 2))
    for idx, trigger in enumerate((EA_DEALS_URL, EA_HOME_URL)):
        if time.time() >= deadline:
            break
        if stats.get("hook_unauthenticated") and int(stats.get("graphql_requests_seen") or 0) > 0:
            break
        if owned_items and stats.get("browser_auth_ok"):
            break
        wait_until = "load" if idx == 0 else "domcontentloaded"
        try:
            page.goto(
                trigger,
                wait_until=wait_until,
                timeout=min(30, timeout_s) * 1000,
            )
        except Exception:  # noqa: BLE001
            pass
        ensure_ea_graphql_hook(page)
        while time.time() < deadline:
            auth_ok, owned_batch, hook_stats = drain_ea_graphql_hook(page)
            _merge_owned_items(owned_items, owned_seen, owned_batch)
            stats["owned_hook_items"] = len(owned_items)
            if hook_stats.get("hook_unauthenticated"):
                stats["hook_unauthenticated"] = True
            if auth_ok:
                stats["browser_auth_ok"] = True
            if stats.get("hook_unauthenticated") and int(stats.get("graphql_requests_seen") or 0) > 0:
                break
            if owned_items and stats.get("browser_auth_ok"):
                break
            if idx == 0 and time.time() < min_dwell_deadline:
                page.wait_for_timeout(500)
                continue
            if idx > 0 or time.time() >= min_dwell_deadline:
                break
            page.wait_for_timeout(500)

    stats["final_url"] = getattr(page, "url", None) or ""
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        html = ""
    stats["login_page"] = is_ea_login_page(html, stats["final_url"])
    stats["session_expired_page"] = is_ea_session_expired_page(html, stats["final_url"])
    cookies = ctx.cookies()

    if stats.get("browser_auth_ok") or owned_items:
        stats["token_captured"] = True
        return SniffResult(
            token=EA_COOKIE_SESSION,
            cookies=cookies,
            owned_items=owned_items,
            debug=stats,
        )

    _ea_session_failure(stats, cookies)


def sniff_ea_bearer(
    ctx: Any,
    page: Any,
    *,
    trigger_urls: tuple[str, ...] = EA_LIBRARY_URLS,
    timeout_s: int = 45,
    debug_out: dict[str, Any] | None = None,
) -> SniffResult:
    """Open trigger pages and capture Juno GraphQL auth (Bearer or browser cookies)."""
    captured: dict[str, str] = {}
    stats: dict[str, Any] = debug_out if debug_out is not None else {}
    stats.setdefault("graphql_requests_seen", 0)
    stats.setdefault("graphql_with_auth", 0)
    stats.setdefault("browser_auth_ok", False)
    stats.setdefault("hook_unauthenticated", False)
    stats.setdefault("token_captured", False)
    stats.setdefault("owned_hook_items", 0)
    stats["trigger_urls"] = list(trigger_urls)
    owned_items: list[dict] = []
    owned_seen: set[str] = set()

    install_ea_graphql_hook(ctx)
    ensure_ea_graphql_hook(page)

    def on_request(request: Any) -> None:
        url = getattr(request, "url", None) or ""
        if EA_GRAPHQL_HOST not in url.lower():
            return
        stats["graphql_requests_seen"] = int(stats["graphql_requests_seen"]) + 1
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = normalize_bearer(auth)
        if token:
            stats["graphql_with_auth"] = int(stats["graphql_with_auth"]) + 1
            captured["token"] = token

    ctx.on("request", on_request)

    def on_response(response: Any) -> None:
        try:
            url = getattr(response, "url", None) or ""
            if EA_GRAPHQL_HOST not in url.lower():
                return
            if int(getattr(response, "status", 0) or 0) != 200:
                return
            payload = response.json()
            if not isinstance(payload, dict):
                return
            batch = ea_graphql_owned_items(payload)
            if batch:
                _merge_owned_items(owned_items, owned_seen, batch)
                stats["owned_hook_items"] = len(owned_items)
            if ea_graphql_authenticated(payload):
                stats["browser_auth_ok"] = True
                captured["token"] = EA_COOKIE_SESSION
        except Exception:  # noqa: BLE001
            pass

    ctx.on("response", on_response)
    deadline = time.time() + timeout_s
    for trigger in trigger_urls:
        if time.time() >= deadline:
            break
        if stats.get("hook_unauthenticated") and int(stats.get("graphql_requests_seen") or 0) > 0:
            break
        if owned_items and (
            captured.get("token") == EA_COOKIE_SESSION
            or stats.get("browser_auth_ok")
            or (captured.get("token") and captured.get("token") != EA_COOKIE_SESSION)
        ):
            break
        try:
            page.goto(trigger, wait_until="domcontentloaded", timeout=min(25, timeout_s) * 1000)
        except Exception:  # noqa: BLE001
            pass
        ensure_ea_graphql_hook(page)
        while time.time() < deadline:
            auth_ok, owned_batch, hook_stats = drain_ea_graphql_hook(page)
            _merge_owned_items(owned_items, owned_seen, owned_batch)
            stats["owned_hook_items"] = len(owned_items)
            if hook_stats.get("hook_unauthenticated"):
                stats["hook_unauthenticated"] = True
            if auth_ok:
                stats["browser_auth_ok"] = True
                captured["token"] = EA_COOKIE_SESSION
            if captured.get("token") and captured.get("token") != EA_COOKIE_SESSION:
                pass
            if stats.get("hook_unauthenticated") and int(stats.get("graphql_requests_seen") or 0) > 0:
                break
            if owned_items and (
                captured.get("token") == EA_COOKIE_SESSION
                or stats.get("browser_auth_ok")
                or (captured.get("token") and captured.get("token") != EA_COOKIE_SESSION)
            ):
                break
            page.wait_for_timeout(500)
        if owned_items and (
            captured.get("token") == EA_COOKIE_SESSION
            or stats.get("browser_auth_ok")
            or (captured.get("token") and captured.get("token") != EA_COOKIE_SESSION)
        ):
            break

    stats["final_url"] = getattr(page, "url", None) or ""
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        html = ""
    stats["login_page"] = is_ea_login_page(html, stats["final_url"])
    stats["session_expired_page"] = is_ea_session_expired_page(html, stats["final_url"])

    token = captured.get("token") or ""
    cookies = ctx.cookies()
    stats["token_captured"] = bool(token)

    if not token:
        _ea_session_failure(stats, cookies)

    if token == EA_COOKIE_SESSION:
        return SniffResult(token=token, cookies=cookies, owned_items=owned_items, debug=stats)

    probe = probe_ea_token(token, cookies)
    if not probe.get("ok"):
        if stats.get("browser_auth_ok") or owned_items:
            return SniffResult(
                token=EA_COOKIE_SESSION,
                cookies=cookies,
                owned_items=owned_items,
                debug=stats,
            )
        raise EaAuthError(probe.get("error") or "EA Bearer token rejected — reconnect EA App.")
    return SniffResult(token=token, cookies=cookies, owned_items=owned_items, debug=stats)


def fetch_owned_games_browser(
    profile_path: Path,
    *,
    headless: bool = True,
    timeout_s: int = 45,
) -> list[dict]:
    """Load EA deals page and pull owned games via in-page Juno APQ (hook fallback)."""
    items: list[dict] = []
    seen: set[str] = set()

    with launch_ea_profile(profile_path, visible=not headless) as ctx:
        install_ea_graphql_hook(ctx)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_ea_graphql_hook(page)
        try:
            page.goto(EA_DEALS_URL, wait_until="load", timeout=min(30, timeout_s) * 1000)
        except Exception:  # noqa: BLE001
            pass
        ensure_ea_graphql_hook(page)
        try:
            page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            pass
        _ensure_ea_deals_ready(page, dwell_ms=2500)
        try:
            pw_owned = fetch_owned_games_playwright_request(ctx)
        except EaAuthError:
            pw_owned = []
        if pw_owned:
            return pw_owned
        for attempt in range(3):
            try:
                items = fetch_owned_games_inpage(page)
            except EaAuthError:
                items = []
            if items:
                return items
            if attempt < 2:
                _ensure_ea_deals_ready(page, dwell_ms=3000)

        deadline = time.time() + timeout_s
        for trigger in EA_LIBRARY_URLS:
            if items:
                break
            try:
                page.goto(trigger, wait_until="domcontentloaded", timeout=min(25, timeout_s) * 1000)
            except Exception:  # noqa: BLE001
                pass
            ensure_ea_graphql_hook(page)
            while time.time() < deadline:
                _auth_ok, owned, _stats = drain_ea_graphql_hook(page)
                _merge_owned_items(items, seen, owned)
                if items:
                    break
                page.wait_for_timeout(500)

    return items
