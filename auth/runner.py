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
    base: dict[str, Any] = {
        "headless": False,
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
        # --disable-blink-features=AutomationControlled is the single most
        # important Cloudflare-bypass flag: without it, navigator.webdriver is
        # exposed *before* our init script runs, which Turnstile detects and
        # locks into a permanent challenge loop.
        "args": [
            "--no-first-run",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-default-browser-check",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    # Fallback UA only used if we have to fall back to bundled Chromium —
    # overriding the UA on real Chrome makes Cloudflare suspicious because the
    # value won't match the actual binary version Playwright is driving.
    fallback_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    try:
        context = p.chromium.launch_persistent_context(user_data, channel="chrome", **base)
    except Exception:
        context = p.chromium.launch_persistent_context(
            user_data, **base, user_agent=fallback_ua
        )
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


EPIC_WISHLIST_URL = "https://store.epicgames.com/en-US/wishlist"


def _extract_epic_wishlist_inline(page, context, session) -> dict[str, str]:
    """Wait until store.epicgames.com/wishlist GraphQL succeeds, then save that cookie.

    Storefront is behind aggressive Cloudflare Turnstile — the user may need to
    click the checkbox manually. We sniff the live Cookie header from a 200
    wishlist GraphQL response (proven to work) and never re-validate from
    Python (cf_clearance is UA/TLS-bound to the browser).
    """
    sniffed: dict[str, str] = {}

    def on_response(response) -> None:
        if sniffed:
            return
        try:
            if "store.epicgames.com/graphql" not in response.url:
                return
            req = response.request
            body = req.post_data or ""
            if "Wishlist" not in body and "wishlistItems" not in body:
                return
            if response.status != 200:
                return
            payload = response.json()
            data = payload.get("data") or {}
            if "Wishlist" not in data:
                return
            cookie = (req.headers.get("cookie") or "").strip()
            if cookie:
                sniffed["EPIC_STORE_COOKIE"] = cookie
        except Exception:  # noqa: BLE001
            pass

    page.on("response", on_response)
    try:
        page.goto(EPIC_WISHLIST_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        cookie = sniffed.get("EPIC_STORE_COOKIE", "").strip()
        if cookie:
            return {"EPIC_STORE_COOKIE": cookie}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            url = (page.url or "").lower()
            if "challenge" in url or "cloudflare" in url:
                msg = "Cloudflare challenge — click the checkbox if shown."
            elif "login" in url or "id.epicgames.com" in url:
                msg = "Sign in to your Epic account in the browser window."
            elif "epicgames.com" not in url:
                msg = "Open store.epicgames.com/wishlist after signing in."
            elif "store.epicgames.com" not in url:
                msg = "Almost there — head to store.epicgames.com/wishlist once signed in."
            else:
                msg = "On the wishlist page? Give it a moment to load."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture a working Epic storefront session — sign in at "
        "store.epicgames.com/wishlist, clear any Cloudflare challenge, and let "
        "your wishlist finish loading."
    )


XBOX_WISHLIST_URL = "https://www.xbox.com/en-us/wishlist"
XBOX_WISHLIST_POLL_SEC = 2.5


def _parse_xbox_preloaded_state(html: str) -> dict | None:
    """Carve ``window.__PRELOADED_STATE__ = { ... }`` out of the SSR HTML.

    The global is consumed and deleted by React after hydration so we never
    see it on ``window``; the raw assignment is always in the response body.
    """
    marker = "window.__PRELOADED_STATE__"
    idx = html.find(marker)
    if idx == -1:
        return None
    eq = html.find("=", idx + len(marker))
    if eq == -1:
        return None
    start = eq + 1
    while start < len(html) and html[start] in " \t\r\n":
        start += 1
    if start >= len(html) or html[start] != "{":
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _xbox_signed_in_state(context) -> dict | None:
    """Fetch xbox.com/wishlist with the persistent cookies and return the
    parsed state when ``user.isSignedIn`` is true (else ``None``)."""
    try:
        resp = context.request.get(XBOX_WISHLIST_URL, timeout=20000)
    except Exception:  # noqa: BLE001
        return None
    if resp.status >= 400:
        return None
    try:
        html = resp.text()
    except Exception:  # noqa: BLE001
        return None
    state = _parse_xbox_preloaded_state(html)
    if not state:
        return None
    user = state.get("user") or {}
    if not user.get("isSignedIn"):
        return None
    page_meta = (state.get("pageRequestMetadata") or {}).get("/wishlist") or {}
    err = page_meta.get("error") or {}
    if err.get("httpStatusCode") == 403:
        # MSA cookie present but xbox.com hasn't issued the wishlist auth
        # token yet — wait for the next poll cycle.
        return None
    return state


def _extract_xbox_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open xbox.com/wishlist, wait for MSA sign-in (detected via SSR HTML),
    then return a marker cred. The real credential is the persistent profile.
    """
    try:
        page.goto(XBOX_WISHLIST_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    last_signin_check = False
    while time.time() < deadline:
        state = _xbox_signed_in_state(context)
        if state is not None:
            # Reload the visible page so the user sees their signed-in
            # wishlist before the window closes (xbox.com's React doesn't
            # always pick up MSA cookies on the same render cycle).
            try:
                page.goto(XBOX_WISHLIST_URL, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass
            return {"XBOX_WISHLIST_PROFILE": "ready"}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            url = (page.url or "").lower()
            if "login.live.com" in url or "login.microsoftonline" in url or "signin" in url:
                msg = "Sign in to your Microsoft account in the browser window."
            elif "xbox.com" not in url:
                msg = "Open xbox.com/wishlist after signing in."
            elif last_signin_check:
                msg = "Signed in \u2014 waiting for xbox.com to issue your wishlist session."
            else:
                msg = "On the wishlist page? Sign in via the Sign in link if you haven't already."
            session.emit("waiting_for_user", {"message": msg})

        last_signin_check = bool(state)
        page.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect an Xbox sign-in \u2014 sign in to xbox.com/wishlist "
        "and keep the window open until it closes."
    )


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


EXTRACTORS = {
    "battlenet": lambda page, ctx: _extract_battlenet(ctx),
    "nintendo": lambda page, ctx: _extract_nintendo(ctx),
    "gog": lambda page, ctx: _extract_gog(ctx),
    "psn": lambda page, ctx: _extract_psn(page, ctx),
    "steam": lambda page, ctx: extract_steam(page, ctx),
    "itch": lambda page, ctx: extract_itch(page, ctx),
    "itad": lambda page, ctx: extract_itad(page, ctx),
    "xbox": lambda page, ctx: extract_xbox(page, ctx),
    "xbox_wishlist": lambda page, ctx: _extract_xbox_wishlist_inline(page, ctx, None),
    "ubisoft": lambda page, ctx: _extract_ubisoft(page, ctx),
    "epic_wishlist": lambda page, ctx: _extract_epic_wishlist_inline(page, ctx, None),
}

# Custom wait/extract loops — not the URL-pattern path in run_browser_auth.
INLINE_PROVIDERS = {"psn", "steam", "itch", "itad", "xbox", "xbox_wishlist", "ubisoft", "epic_wishlist"}


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
        "psn": "Sign in to PlayStation Store (Sign In, top-right). Keep this window open.",
        "steam": "Sign in to Steam. We'll save your API key automatically.",
        "itch": "Sign in to itch.io. We'll save your API key automatically.",
        "itad": "Sign in to IsThereAnyDeal. We'll register an app and save your API key.",
        "xbox": "Sign in to OpenXBL with your Microsoft account. We'll save your API key automatically.",
        "xbox_wishlist": (
            "Sign in to xbox.com with your Microsoft account. We'll detect your "
            "wishlist session automatically \u2014 no need to refresh the page."
        ),
        "epic_wishlist": (
            "Sign in if prompted, then stay on store.epicgames.com/wishlist "
            "until your wishlist finishes loading. Clear any Cloudflare check if shown."
        ),
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
            elif provider == "epic_wishlist":
                creds = _extract_epic_wishlist_inline(page, context, session)
            elif provider == "xbox_wishlist":
                creds = _extract_xbox_wishlist_inline(page, context, session)
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
