"""Playwright headed sign-in and credential extraction."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse

from auth.api_keys import (
    extract_itad,
    extract_itch,
    extract_steam,
    extract_xbox,
)
from auth.registry import spec_for
from auth.secrets import profile_dir

SUCCESS_WAIT_SEC = 300
POLL_SEC = 0.5
PSN_STORE_URL = "https://store.playstation.com/en-us/"
PSN_SSOCOOKIE_URL = "https://ca.account.sony.com/api/v1/ssocookie"
PSN_SSOCOOKIE_INTERVAL_SEC = 10

_STEALTH_INIT = r"""
(() => {
  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true }); } catch (e) {}
  try {
    const orig = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
    if (orig) Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });
    Object.defineProperty(navigator, 'plugins', {
      get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
      ],
      configurable: true,
    });
  } catch (e) {}
  try { window.chrome = window.chrome || { runtime: {}, app: { isInstalled: false } }; } catch (e) {}
  try {
    const oq = window.navigator.permissions && window.navigator.permissions.query;
    if (oq) {
      window.navigator.permissions.query = (p) =>
        p && p.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : oq.call(window.navigator.permissions, p);
    }
  } catch (e) {}
  try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }); } catch (e) {}
  try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 }); } catch (e) {}
  try { Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 }); } catch (e) {}
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
})();
"""


def _launch_persistent_context(p, user_data: str):
    """Prefer installed Chrome — bundled Chromium triggers Cloudflare bot challenges."""
    common: dict[str, Any] = {
        "headless": False,
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "args": ["--no-first-run"],
        "ignore_default_args": ["--enable-automation", "--no-sandbox"],
    }
    try:
        context = p.chromium.launch_persistent_context(user_data, channel="chrome", **common)
    except Exception:
        context = p.chromium.launch_persistent_context(user_data, **common)
    context.add_init_script(_STEALTH_INIT)

    # Rewrite target=_blank to current tab so dashboard scraping never opens new
    # tabs that surprise the user. Affects fully-isolated profiles only.
    def _on_new_page(new_page) -> None:
        try:
            url = new_page.url
            new_page.close()
            if url and url not in ("about:blank", ""):
                old = context.pages[0] if context.pages else context.new_page()
                old.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass

    context.on("page", _on_new_page)
    return context


class AuthSession:
    __slots__ = ("id", "provider", "events", "_listeners", "_finished", "_lock")

    def __init__(self, session_id: str, provider: str) -> None:
        self.id = session_id
        self.provider = provider
        self.events: queue.Queue[tuple[str, dict]] = queue.Queue()
        self._listeners: list[Callable[[str, dict], None]] = []
        self._finished = threading.Event()
        self._lock = threading.Lock()

    def emit(self, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            self.events.put((event, data))
            for cb in list(self._listeners):
                try:
                    cb(event, data)
                except Exception:
                    pass

    def add_listener(self, callback: Callable[[str, dict], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def finish(self) -> None:
        self._finished.set()
        self.emit("done", {})

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)


def _cookie_header(cookies: list[dict], domains: tuple[str, ...]) -> str:
    parts: list[str] = []
    for c in cookies:
        domain = c.get("domain") or ""
        if not any(d in domain for d in domains):
            continue
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _extract_battlenet(context) -> dict[str, str]:
    cookies = context.cookies()
    header = _cookie_header(cookies, (".battle.net", "battle.net"))
    if not header:
        raise RuntimeError("No Battle.net cookies found — finish signing in at account.battle.net")
    return {"BATTLENET_COOKIE": header}


def _extract_nintendo(context) -> dict[str, str]:
    cookies = context.cookies()
    header = _cookie_header(cookies, ("nintendo.com",))
    if not header:
        raise RuntimeError("No Nintendo cookies found — open ec.nintendo.com after signing in")
    return {"NINTENDO_COOKIE": header}


def _extract_gog(context) -> dict[str, str]:
    cookies = context.cookies()
    gog_al = next((c["value"] for c in cookies if c.get("name") == "gog-al"), "")
    if not gog_al:
        header = _cookie_header(cookies, ("gog.com",))
        if not header:
            raise RuntimeError("No GOG session — sign in at gog.com")
        return {"GOG_AL": header.split("gog-al=")[-1].split(";")[0] if "gog-al=" in header else header}
    return {"GOG_AL": gog_al}


def _psn_cookie(context) -> str:
    for c in context.cookies():
        if c.get("name") == "npsso" and c.get("value"):
            return c["value"]
    return ""


def _validate_npsso(npsso: str) -> bool:
    try:
        from psn_client import validate_npsso

        validate_npsso(npsso)
        return True
    except Exception:
        return False


def _psn_on_blocked_account_page(url: str, body: str) -> bool:
    u = (url or "").lower()
    b = (body or "").lower()
    if "global_error" in u:
        return True
    if "sonyacct/signin" in u or "my.account.sony.com" in u:
        if "something went wrong" in b or "global_error" in u:
            return True
    return False


def _fetch_npsso_background(page, context) -> str:
    """Fetch npsso via in-page request — never navigate away from the store."""
    npsso = _psn_cookie(context)
    if npsso:
        return npsso
    try:
        result = page.evaluate(
            """async () => {
                try {
                    const res = await fetch('https://ca.account.sony.com/api/v1/ssocookie', {
                        credentials: 'include',
                        headers: { Accept: 'application/json' },
                    });
                    if (!res.ok) return '';
                    const data = await res.json();
                    if (data && data.error) return '';
                    return (data && data.npsso) ? data.npsso : '';
                } catch {
                    return '';
                }
            }"""
        )
        if isinstance(result, str) and result:
            return result
    except Exception:
        pass
    return _psn_cookie(context)


def _extract_psn(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Wait for sign-in on the PlayStation Store, then capture a valid npsso."""
    deadline = time.time() + SUCCESS_WAIT_SEC
    last_ssocookie = 0.0
    tried_cookie: set[str] = set()
    last_msg = 0.0
    while time.time() < deadline:
        url = page.url or ""

        # Always re-check by fetching from ssocookie endpoint first; that's
        # the source of truth, not the stale cookie that may be in the jar.
        now = time.time()
        if now - last_ssocookie >= PSN_SSOCOOKIE_INTERVAL_SEC:
            last_ssocookie = now
            fresh = _fetch_npsso_background(page, context)
            if fresh and fresh not in tried_cookie:
                if _validate_npsso(fresh):
                    return {"PSN_NPSSO": fresh}
                tried_cookie.add(fresh)

        # Also try the cookie directly (cheap)
        cookie_val = _psn_cookie(context)
        if cookie_val and cookie_val not in tried_cookie:
            if _validate_npsso(cookie_val):
                return {"PSN_NPSSO": cookie_val}
            tried_cookie.add(cookie_val)

        try:
            body = page.content()
        except Exception:
            body = ""

        if _psn_on_blocked_account_page(url, body):
            if session and now - last_msg > 6:
                last_msg = now
                session.emit(
                    "waiting_for_user",
                    {"message": "Use Sign In on the PlayStation Store (top-right) to continue"},
                )
            try:
                page.goto(PSN_STORE_URL, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            continue

        if session and now - last_msg > 6:
            last_msg = now
            session.emit(
                "waiting_for_user",
                {
                    "message": (
                        "Signed in to PlayStation? Click anything on the page so Sony "
                        "issues a fresh session cookie."
                    )
                    if "store.playstation.com" in url.lower()
                    else "Sign in on the PlayStation Store (Sign In, top-right)."
                },
            )

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture a PSN session — sign in on the PlayStation Store (Sign In, top-right) "
        "and keep this window open until it closes."
    )


def _extract_epic_wishlist(context) -> dict[str, str]:
    cookies = context.cookies()
    header = _cookie_header(cookies, ("epicgames.com",))
    if not header:
        raise RuntimeError("No Epic storefront cookies — sign in at store.epicgames.com")
    return {"EPIC_STORE_COOKIE": header}


def _extract_ubisoft(page, context) -> dict[str, str]:
    captured: dict[str, str] = {}

    def on_request(request) -> None:
        if "public-ubiservices.ubi.com" not in request.url:
            return
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        session = request.headers.get("ubi-sessionid") or request.headers.get("Ubi-SessionId")
        app_id = request.headers.get("ubi-appid") or request.headers.get("Ubi-AppId")
        if auth:
            captured["UBISOFT_AUTH"] = auth
        if session:
            captured["UBISOFT_SESSION_ID"] = session
        if app_id:
            captured["UBISOFT_APP_ID"] = app_id

    page.on("request", on_request)
    page.goto("https://www.ubisoft.com/en-us/ubisoft-connect", wait_until="domcontentloaded")
    deadline = time.time() + SUCCESS_WAIT_SEC
    while time.time() < deadline:
        if captured.get("UBISOFT_AUTH") and captured.get("UBISOFT_SESSION_ID"):
            return captured
        page.wait_for_timeout(int(POLL_SEC * 1000))
    raise RuntimeError(
        "Ubisoft API headers not captured — browse to your library on ubisoft.com while the window is open"
    )


def _extract_epic_oauth(page) -> dict[str, str]:
    deadline = time.time() + SUCCESS_WAIT_SEC
    while time.time() < deadline:
        try:
            body = page.content()
        except Exception:
            page.wait_for_timeout(500)
            continue
        m = re.search(r'"authorizationCode"\s*:\s*"([^"]+)"', body)
        if m:
            code = m.group(1)
            # Exchange immediately and persist refresh token via epic_client
            from epic_client import EpicClient

            client = EpicClient(auth_code=code)
            client.login()
            return {"EPIC_AUTH_CODE": code}
        page.wait_for_timeout(500)
    raise RuntimeError("Epic authorization code not received — complete sign-in in the browser window")


EXTRACTORS = {
    "battlenet": lambda page, ctx: _extract_battlenet(ctx),
    "nintendo": lambda page, ctx: _extract_nintendo(ctx),
    "gog": lambda page, ctx: _extract_gog(ctx),
    "psn": lambda page, ctx: _extract_psn(page, ctx),
    "steam": lambda page, ctx: extract_steam(page, ctx),
    "itch": lambda page, ctx: extract_itch(page, ctx),
    "itad": lambda page, ctx: extract_itad(page, ctx),
    "xbox": lambda page, ctx: extract_xbox(page, ctx),
    "epic_wishlist": lambda page, ctx: _extract_epic_wishlist(ctx),
    "ubisoft": lambda page, ctx: _extract_ubisoft(page, ctx),
    "epic": lambda page, ctx: _extract_epic_oauth(page),
}

# Custom wait/extract loops — not the URL-pattern path in run_browser_auth.
INLINE_PROVIDERS = {"psn", "steam", "itch", "itad", "xbox", "ubisoft", "epic"}


def run_browser_auth(provider: str, session: AuthSession) -> dict[str, str] | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    spec = spec_for(provider)
    extractor = EXTRACTORS.get(provider)
    if not extractor:
        raise RuntimeError(f"No browser extractor for {provider}")

    user_data = str(profile_dir(provider))
    _CONNECT_HINTS = {
        "psn": "Sign in on the PlayStation Store (Sign In, top-right). Leave this window open.",
        "steam": "Sign in to Steam. We'll register your API key automatically.",
        "itch": "Sign in to itch.io. We'll save your API key automatically.",
        "itad": "Sign in to IsThereAnyDeal. We'll register an app and save your API key.",
        "xbox": "Sign in to OpenXBL (xbl.io) with Microsoft. Leave this window open.",
    }
    session.emit(
        "waiting_for_user",
        {"message": _CONNECT_HINTS.get(provider, f"Sign in to {spec.label} in the browser window")},
    )

    with sync_playwright() as p:
        context = _launch_persistent_context(p, user_data)
        page = context.pages[0] if context.pages else context.new_page()

        if provider in INLINE_PROVIDERS:
            if provider == "psn":
                try:
                    page.goto(PSN_STORE_URL, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
                creds = _extract_psn(page, context, session)
            elif provider in ("steam", "itch", "itad", "xbox"):
                try:
                    page.goto(spec.login_url, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
                api_extractors = {
                    "steam": extract_steam,
                    "itch": extract_itch,
                    "itad": extract_itad,
                    "xbox": extract_xbox,
                }
                creds = api_extractors[provider](page, context, session)
            elif provider != "ubisoft":
                page.goto(spec.login_url, wait_until="domcontentloaded")
                session.emit("signed_in", {"url": page.url})
                creds = extractor(page, context)
            else:
                session.emit("signed_in", {"url": page.url})
                creds = extractor(page, context)
            context.close()
            return creds

        page.goto(spec.login_url, wait_until="domcontentloaded")
        pattern = re.compile(spec.success_url_pattern, re.I)
        deadline = time.time() + SUCCESS_WAIT_SEC
        signed_in = False
        while time.time() < deadline:
            url = page.url or ""
            if pattern.search(url):
                signed_in = True
                break
            # Nintendo may need explicit navigation after login
            if provider == "nintendo" and "login" not in url.lower():
                try:
                    page.goto(spec.login_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
                if pattern.search(page.url or ""):
                    signed_in = True
                    break
            page.wait_for_timeout(int(POLL_SEC * 1000))

        if not signed_in and provider in ("nintendo", "psn", "gog"):
            # Allow extraction attempt even if URL pattern didn't match
            signed_in = True

        if not signed_in:
            context.close()
            return None

        session.emit("signed_in", {"url": page.url})
        creds = extractor(page, context)
        context.close()
        return creds
