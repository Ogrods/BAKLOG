"""Headed Chrome/Edge sign-in and credential extraction via CDP."""

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
from auth.cdp_browser import is_blank_browser_url, launch_persistent_profile
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
    from battlenet_client import probe_session

    probe_session(header)
    return {"BATTLENET_COOKIE": header}


BATTLENET_GAMES_URL = "https://account.battle.net/games"


def _battlenet_has_session(context) -> bool:
    """True when the Playwright context can read the games-and-subs API."""
    from battlenet_client import ACCOUNT_URL

    try:
        resp = context.request.get(ACCOUNT_URL, timeout=30_000)
        if resp.status == 200:
            body = resp.text().strip()
            return body.startswith("{") or body.startswith("[")
        if resp.status in (401, 403):
            return False
    except Exception:  # noqa: BLE001
        pass
    return False


def _extract_battlenet_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Open account.battle.net/games and save cookies only after the library API works."""
    try:
        page.goto(BATTLENET_GAMES_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        if _battlenet_has_session(context):
            header = _cookie_header(context.cookies(), (".battle.net", "battle.net"))
            if not header:
                break
            from battlenet_client import probe_session

            probe_session(header)
            if session:
                session.emit("signed_in", {"url": page.url or BATTLENET_GAMES_URL})
            return {"BATTLENET_COOKIE": header}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            url = (page.url or "").lower()
            if "login" in url or "signin" in url or "authorize" in url:
                msg = "Sign in to your Battle.net account in the browser window."
            elif "battle.net" not in url:
                msg = "Open account.battle.net/games after signing in."
            else:
                msg = (
                    "On your Games page? Wait until your library list finishes loading, "
                    "then we'll save the session automatically."
                )
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not verify a Battle.net library session — sign in at account.battle.net/games, "
        "wait until your Games list loads, then click Connect again."
    )


def _extract_nintendo(context) -> dict[str, str]:
    cookies = context.cookies()
    header = _cookie_header(cookies, ("nintendo.com",))
    if not header:
        raise RuntimeError("No Nintendo cookies found — open ec.nintendo.com after signing in")
    return {"NINTENDO_COOKIE": header}


NINTENDO_ACCOUNT_URL = "https://ec.nintendo.com/my/transactions/"
# Nintendo session cookies that prove we can read the eShop purchase history.
# Capturing any nintendo.com cookie isn't enough — sign-in completes on
# accounts.nintendo.com, but the eShop session cookies only get set once we're
# actually on ec.nintendo.com, so we must land there before reading the jar.
_NINTENDO_SESSION_COOKIES = ("MIST", "JViDD", "_gh_sess", "NASID", "ecsid")


def _nintendo_has_session(context) -> bool:
    """True when known eShop session cookies exist on ec.nintendo.com."""
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if not domain.startswith("ec.nintendo.com"):
            continue
        name = c.get("name") or ""
        if name in _NINTENDO_SESSION_COOKIES and c.get("value"):
            return True
    return False


def _nintendo_session_has_id_token(context) -> bool:
    """Verify /api/auth/session returns an idToken (GraphQL prerequisite)."""
    try:
        from nintendo_client import SESSION_URL, probe_session_id_token

        return bool(probe_session_id_token(context.request.get).get("ok"))
    except Exception:
        return False


def _extract_nintendo_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Wait for Nintendo sign-in, then auto-navigate to ec.nintendo.com to capture cookies.

    The earlier flow errored with "open ec.nintendo.com after signing in" because
    sign-in lands on accounts.nintendo.com and the eShop cookies aren't set until
    you're back on ec.nintendo.com. We now drive that navigation automatically and
    only fall back to asking the user if it still doesn't land.
    """
    try:
        page.goto(NINTENDO_ACCOUNT_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    last_nav = 0.0
    while time.time() < deadline:
        live = [pg for pg in context.pages if not pg.is_closed]
        main = live[0] if live else context.new_page()
        url = (main.url or "").lower()
        signed_in = "ec.nintendo.com" in url and "login" not in url and "connect" not in url

        # Once signed in (we've returned to ec.nintendo.com), the eShop session
        # cookies should be present — capture and finish.
        if signed_in and _nintendo_has_session(context) and _nintendo_session_has_id_token(context):
            header = _cookie_header(context.cookies(), ("nintendo.com",))
            if header:
                return {"NINTENDO_COOKIE": header}

        # User finished sign-in but we're parked on accounts.nintendo.com / home —
        # auto-redirect to the transactions page so the eShop cookies get set.
        on_account = (
            "accounts.nintendo.com" in url
            or "nintendo.com" in url
            and "ec.nintendo.com" not in url
        )
        if on_account and "login" not in url and "signin" not in url and "authorize" not in url:
            now = time.time()
            if now - last_nav > 4:
                last_nav = now
                try:
                    main.bring_to_front()
                except Exception:
                    pass
                try:
                    main.goto(NINTENDO_ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
                except Exception:
                    pass

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            if "login" in url or "signin" in url or "authorize" in url:
                msg = "Sign in to your Nintendo Account in the browser window."
            elif on_account:
                msg = "Signed in — opening your eShop transactions page to capture the session."
            else:
                msg = "Loading your Nintendo eShop transactions — keep the window open."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    # Last resort: session cookies + idToken probe (not merely any nintendo.com cookie).
    if _nintendo_has_session(context) and _nintendo_session_has_id_token(context):
        header = _cookie_header(context.cookies(), ("nintendo.com",))
        if header:
            return {"NINTENDO_COOKIE": header}
    raise RuntimeError(
        "No Nintendo session captured — sign in, then make sure the eShop transactions page "
        "at ec.nintendo.com finished loading. Close any blank tab and click Connect again if needed."
    )


EPIC_REDIRECT_MARKER = "id/api/redirect"


def _epic_code_from_text(text: str) -> str:
    """Pull the authorizationCode out of Epic's redirect JSON (or HTML-wrapped JSON)."""
    if not text:
        return ""
    try:
        data = json.loads(text)
        code = data.get("authorizationCode") if isinstance(data, dict) else None
        if isinstance(code, str) and code.strip():
            return code.strip()
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r'"authorizationCode"\s*:\s*"([A-Za-z0-9_\-]+)"', text)
    return m.group(1) if m else ""


def _extract_epic_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Sign in to Epic in the managed window, then auto-capture + exchange the code.

    Epic's launcher client redirects post-login to id/api/redirect, which renders a
    JSON body containing a one-time `authorizationCode`. We scrape it and exchange it
    for a refresh token immediately (codes are single-use), persisting the session so
    the fetcher can reuse it. On any failure the user can still paste the code manually.
    """
    login_url = spec_for("epic").login_url
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    while time.time() < deadline:
        live = [pg for pg in context.pages if not pg.is_closed]
        main = live[0] if live else context.new_page()
        url = (main.url or "").lower()

        if EPIC_REDIRECT_MARKER in url:
            body = ""
            try:
                body = main.evaluate("() => document.body ? document.body.innerText : ''") or ""
            except Exception:
                body = ""
            code = _epic_code_from_text(body)
            if not code:
                try:
                    code = _epic_code_from_text(main.content())
                except Exception:
                    code = ""
            if code:
                from epic_client import EpicAuthError, EpicClient, default_epic_cache_dir

                try:
                    EpicClient(auth_code=code, cache_dir=default_epic_cache_dir()).login()
                except EpicAuthError as exc:
                    raise RuntimeError(
                        f"Epic rejected the captured code ({exc}). Refresh the Epic page so a new "
                        "code appears, or paste the authorizationCode into the fallback field below."
                    ) from exc
                return {"EPIC_AUTH_CODE": code}

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            if "login" in url or "id.epicgames.com" in url:
                msg = "Sign in to your Epic account in the browser window."
            else:
                msg = "Capturing your Epic authorization code — keep the window open."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture your Epic authorization code in time. If the Epic page shows an "
        "authorizationCode, paste it into the fallback field below and click Save key."
    )


def pick_gog_al_from_cookies(cookies: list[dict]) -> str:
    """Return the gog-al session value from Playwright cookie dicts, or \"\"."""
    gog_al = next((c["value"] for c in cookies if c.get("name") == "gog-al" and c.get("value")), "")
    if gog_al:
        return str(gog_al)
    header = _cookie_header(cookies, ("gog.com",))
    if header and "gog-al=" in header:
        return header.split("gog-al=")[-1].split(";")[0].strip()
    if header:
        return header.strip()
    return ""


def _extract_gog(context) -> dict[str, str]:
    gog_al = pick_gog_al_from_cookies(context.cookies())
    if not gog_al:
        raise RuntimeError("No GOG session — sign in at gog.com")
    return {"GOG_AL": gog_al}


def _extract_gog_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Poll for gog-al after the user signs in — do not trust the /en homepage URL."""
    try:
        page.goto("https://www.gog.com/", wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        gog_al = pick_gog_al_from_cookies(context.cookies())
        if gog_al:
            if session:
                session.emit("signed_in", {"url": page.url or "https://www.gog.com/"})
            return {"GOG_AL": gog_al}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            url = (page.url or "").lower()
            if "login" in url or "signin" in url or "auth" in url:
                msg = "Sign in to your GOG account in the browser window."
            else:
                msg = (
                    "Sign in at gog.com if prompted. We'll save your session automatically "
                    "once you're logged in."
                )
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture a GOG session in time — sign in at gog.com in the browser window, "
        "then click Connect again."
    )


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


def _epic_wishlist_graphql_ok(payload: dict) -> bool:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return False
    return "Wishlist" in data


# Sign-in cookies (EPIC_DEVICE is set for anonymous visitors — excluded).
_EPIC_SESSION_COOKIES = (
    "epic_bearer_token",
    "epic_sso",
    "epic_sso_rm",
    "epic_session_ap",
    "epic_session_diesel",
    "epic_session_reload",
    "epic_eg1",
    "refresh_epic_eg1",
)


def _epic_has_session(context) -> bool:
    """True when the profile has Epic account or storefront session cookies."""
    try:
        cookies = context.cookies()
    except Exception:  # noqa: BLE001
        return False
    for c in cookies:
        name = (c.get("name") or "").lower()
        domain = (c.get("domain") or "").lower()
        if not c.get("value") or "epicgames.com" not in domain:
            continue
        if name in _EPIC_SESSION_COOKIES:
            return True
    return False


def _epic_should_open_wishlist(url: str) -> bool:
    """True when we should auto-navigate to the storefront wishlist."""
    u = (url or "").lower()
    if not u or is_blank_browser_url(u):
        return True
    if "challenge" in u or "cloudflare" in u:
        return False
    if "id.epicgames.com" in u and ("/login" in u or "signin" in u):
        return False
    if "store.epicgames.com" in u and "wishlist" in u:
        return False
    if "id.epicgames.com" in u:
        return True
    if "epicgames.com" in u and "store.epicgames.com" not in u:
        return True
    if "store.epicgames.com" in u and "wishlist" not in u:
        return True
    return False


def _extract_epic_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open store.epicgames.com/wishlist, wait for sign-in, return profile marker.

    The saved browser profile (cache/auth/profiles/epic_wishlist) is reused by
    fetch_epic_wishlist.py headlessly. After Epic sign-in we auto-open the
    wishlist (store cookies are often set only once the storefront loads).
    """
    wishlist_loaded = False
    # Reader-thread handlers must NOT call response.json()/getResponseBody — that
    # issues another CDP command and waits on the very thread that pumps the
    # reply, deadlocking until timeout and freezing cookie polling. Just stash
    # candidate responses; the polling thread parses their bodies safely.
    candidates: list[Any] = []

    def on_response(response) -> None:
        try:
            if "store.epicgames.com/graphql" not in (response.url or ""):
                return
            if response.status == 200:
                candidates.append(response)
        except Exception:  # noqa: BLE001
            pass

    def _drain_candidates() -> bool:
        while candidates:
            resp = candidates.pop(0)
            try:
                if _epic_wishlist_graphql_ok(resp.json()):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    page.on("response", on_response)
    try:
        page.goto(EPIC_WISHLIST_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    last_nav = 0.0
    while time.time() < deadline:
        if not wishlist_loaded and _drain_candidates():
            wishlist_loaded = True
        if wishlist_loaded or _epic_has_session(context):
            try:
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass
            return {"EPIC_STORE_COOKIE": "ready"}

        url = page.url or ""
        now = time.time()
        if _epic_should_open_wishlist(url) and now - last_nav > 4:
            last_nav = now
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            try:
                page.goto(EPIC_WISHLIST_URL, wait_until="domcontentloaded", timeout=25_000)
            except Exception:  # noqa: BLE001
                pass

        if session and now - last_msg > 8:
            last_msg = now
            ul = url.lower()
            if "challenge" in ul or "cloudflare" in ul:
                msg = "Cloudflare challenge — click the checkbox if shown."
            elif "login" in ul or ("id.epicgames.com" in ul and "authorize" in ul):
                msg = "Sign in to your Epic account in the browser window."
            elif _epic_should_open_wishlist(url):
                msg = "Signed in — opening your Epic wishlist to capture the session."
            elif "store.epicgames.com" in ul:
                msg = "On the wishlist page? Give it a moment to load."
            else:
                msg = "Sign in, then we'll open store.epicgames.com/wishlist for you."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect Epic wishlist sign-in — sign in at store.epicgames.com/wishlist, "
        "clear any Cloudflare challenge, and let your wishlist finish loading."
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


NINTENDO_WISHLIST_URL = "https://www.nintendo.com/us/wish-list/"
NINTENDO_WISHLIST_POLL_SEC = 2.5


def _nintendo_wishlist_page_ready(html: str, url: str) -> bool:
    """True when the wish-list page looks loaded and not stuck on sign-in only."""
    u = (url or "").lower()
    if "accounts.nintendo.com/login" in u:
        return False
    body = html or ""
    if not body.strip():
        return False
    if "wish-list" not in u and "wishlist" not in u:
        return False
    lower = body.lower()
    if "sign in" in lower and "wish list" not in lower and "wishlist" not in lower:
        return False
    # Empty wishlist copy still counts as a successful session.
    if re.search(r"wish\s*list", lower, re.I):
        return True
    if re.search(r"explore,\s*purchase,\s*or\s*remove", lower, re.I):
        return True
    return "nsuid" in lower or "/store/products/" in lower


def _extract_nintendo_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open nintendo.com/us/wish-list/, wait for sign-in, return marker cred."""
    try:
        page.goto(NINTENDO_WISHLIST_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            html = ""
        url = page.url or ""
        if _nintendo_wishlist_page_ready(html, url):
            try:
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass
            return {"NINTENDO_WISHLIST_PROFILE": "ready"}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            ul = url.lower()
            if "accounts.nintendo.com" in ul or "login" in ul:
                msg = "Sign in to your Nintendo Account in the browser window."
            elif "wish-list" not in ul:
                msg = "Open nintendo.com/us/wish-list/ after signing in."
            else:
                msg = "On the wish list page? Sign in if prompted and wait for it to finish loading."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(NINTENDO_WISHLIST_POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect a Nintendo wish-list session \u2014 sign in at "
        "nintendo.com/us/wish-list/ and keep the window open until it closes."
    )


HUMBLE_LIBRARY_URL = "https://www.humblebundle.com/home/library"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_POLL_SEC = 2.5


def _humble_has_session(context) -> bool:
    """True when the saved profile has a Humble auth cookie."""
    for c in context.cookies():
        name = (c.get("name") or "").lower()
        if name in ("_simpleauth_sess", "csrf_cookie"):
            if c.get("value"):
                return True
    try:
        resp = context.request.get(HUMBLE_ORDERS_API, timeout=15_000)
        if resp.status == 200:
            body = resp.text().strip()
            if body.startswith("[") or body.startswith("{"):
                return True
        if resp.status == 401 or resp.status == 403:
            return False
    except Exception:  # noqa: BLE001
        pass
    return False


def _extract_humble_inline(page, context, session) -> dict[str, str]:
    """Open humblebundle.com/home/library, wait for sign-in, return marker cred."""
    try:
        page.goto(HUMBLE_LIBRARY_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        if _humble_has_session(context):
            try:
                page.goto(HUMBLE_LIBRARY_URL, wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass
            return {"HUMBLE_PROFILE": "ready"}

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            url = (page.url or "").lower()
            if "login" in url or "sign" in url and "library" not in url:
                msg = "Sign in to Humble Bundle in the browser window (email or Google)."
            elif "humblebundle.com" not in url:
                msg = "Open humblebundle.com/home/library after signing in."
            else:
                msg = "On the library page? Finish sign-in if prompted, then wait a moment."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(HUMBLE_POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect a Humble sign-in \u2014 sign in at humblebundle.com/home/library "
        "and keep the window open until it closes."
    )


UBISOFT_SUCCESS_URL = "connect.ubisoft.com/logged-in.html"
UBISOFT_LIBRARY_URLS = (
    "https://connect.ubisoft.com/",
    "https://www.ubisoft.com/en-us/ubisoft-connect/games",
)


def _ubisoft_active_page(live: list) -> object | None:
    """Prefer login/success tabs over the marketing Connect landing page."""
    if not live:
        return None
    for pg in live:
        u = (pg.url or "").lower()
        if (
            "account.ubisoft" in u
            or "connect.ubisoft" in u
            or UBISOFT_SUCCESS_URL in u
        ):
            return pg
    for pg in live:
        u = (pg.url or "").lower()
        if any(x in u for x in ("login", "signin", "authorize", "oauth")):
            return pg
    return live[0]


def _extract_ubisoft(page, context, session: AuthSession | None = None) -> dict[str, str]:
    captured: dict[str, str] = {}

    def on_request(request) -> None:
        if "public-ubiservices.ubi.com" not in request.url:
            return
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        ubi_session = request.headers.get("ubi-sessionid") or request.headers.get("Ubi-SessionId")
        app_id = request.headers.get("ubi-appid") or request.headers.get("Ubi-AppId")
        if auth:
            captured["UBISOFT_AUTH"] = auth
        if ubi_session:
            captured["UBISOFT_SESSION_ID"] = ubi_session
        if app_id:
            captured["UBISOFT_APP_ID"] = app_id

    # Sniff on every page so a request fired from the post-2FA landing tab still counts.
    context.on("request", on_request)
    try:
        page.goto("https://www.ubisoft.com/en-us/ubisoft-connect", wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    seen_success = False
    nudged = 0
    while time.time() < deadline:
        if captured.get("UBISOFT_AUTH") and captured.get("UBISOFT_SESSION_ID"):
            return captured

        live = [pg for pg in context.pages if not pg.is_closed]
        main = _ubisoft_active_page(live) or (live[0] if live else context.new_page())
        if len(live) > 1:
            try:
                main.bring_to_front()
            except Exception:
                pass
        urls = [(pg.url or "").lower() for pg in live]
        on_success = any(UBISOFT_SUCCESS_URL in u for u in urls)

        # Post-2FA we land on connect.ubisoft.com/logged-in.html. That page doesn't
        # call ubiservices on its own, so drive a real tab to the library to trigger
        # the authenticated API requests we sniff for credentials.
        if on_success and not seen_success:
            seen_success = True
            if session:
                session.emit("signed_in", {"url": UBISOFT_SUCCESS_URL})

        if (on_success or seen_success) and nudged < len(UBISOFT_LIBRARY_URLS):
            try:
                main.bring_to_front()
            except Exception:
                pass
            try:
                main.goto(UBISOFT_LIBRARY_URLS[nudged], wait_until="domcontentloaded", timeout=20_000)
            except Exception:
                pass
            nudged += 1

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            joined = " ".join(urls)
            if "account.ubisoft" in joined or "login" in joined:
                msg = (
                    "Finish Ubisoft sign-in and 2FA in the browser window (use the popup if it "
                    "stays open). Close DevTools if you see a yellow 'Debugger paused' banner."
                )
            elif seen_success and not captured:
                msg = "Signed in — opening your Ubisoft games list to finish capturing the session."
            elif not captured:
                msg = "Signed in? Open your Ubisoft Connect games list so we can capture the session."
            else:
                msg = "Almost there — keep the window open while we finish capturing your session."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Ubisoft API headers not captured — sign in at ubisoft.com, complete 2FA, and open your "
        "games library. If a verify step left a blank tab, close it and click Connect again."
    )


def _extract_ea(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Confirm ea.com login, persist profile + web-session Bearer token."""
    from ea_session import (
        EA_DEALS_URL,
        EA_GRAPHQL_HOST,
        EA_LOGIN_URL,
        normalize_bearer,
        probe_ea_token,
    )

    saw_token: dict[str, Any] = {"ok": False, "value": ""}

    def on_request(request) -> None:
        if EA_GRAPHQL_HOST not in (request.url or ""):
            return
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        token = normalize_bearer(auth)
        if token:
            saw_token["ok"] = True
            saw_token["value"] = token

    context.on("request", on_request)
    try:
        page.goto(EA_LOGIN_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    nudged = False
    while time.time() < deadline:
        if saw_token["ok"] and saw_token["value"]:
            cookies = context.cookies()
            if probe_ea_token(saw_token["value"], cookies).get("ok"):
                return {
                    "EA_PROFILE": "ready",
                    "EA_BEARER_TOKEN": saw_token["value"],
                }
            saw_token["ok"] = False
            saw_token["value"] = ""

        url = (page.url or "").lower()
        signed_in = "ea.com" in url and "login" not in url and "signin.ea.com" not in url
        if signed_in and not nudged:
            nudged = True
            if session:
                session.emit("signed_in", {"url": page.url or EA_LOGIN_URL})
            try:
                page.bring_to_front()
            except Exception:
                pass
            try:
                page.goto(EA_DEALS_URL, wait_until="domcontentloaded", timeout=25_000)
            except Exception:
                pass

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            if "signin.ea.com" in url or "/login" in url:
                msg = "Sign in to your EA account in the browser window."
            elif signed_in and not saw_token["ok"]:
                msg = "Signed in — wait for the deals page to finish loading so we can save your session."
            else:
                msg = "Keep the window open while we confirm your EA App session."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "EA session not confirmed — sign in at ea.com, then wait on the deals page "
        "before the window closes."
    )


def _extract_amazon_web(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Confirm Prime Gaming session; durable credential is the saved browser profile."""
    from amazon_web_client import (
        _capture_claims_from_response,
        _poll_prime_collection,
    )

    raw_claims: list[dict[str, Any]] = []
    captured: dict[str, bool] = {"done": False}

    def on_response(resp: Any) -> None:
        _capture_claims_from_response(resp, raw_claims, captured)

    page.on("response", on_response)
    _poll_prime_collection(
        page,
        context,
        deadline=time.time() + SUCCESS_WAIT_SEC,
        raw_claims=raw_claims,
        captured=captured,
        allow_session_only=True,
        start_at_signin=True,
        session=session,
        poll_interval_ms=int(POLL_SEC * 1000),
    )

    if captured["done"]:
        return {"AMAZON_WEB_PROFILE": "ready"}

    raise RuntimeError(
        "Prime Gaming session not confirmed — sign in on the Amazon page, wait for "
        "My Collection (or gaming.amazon.com) to load, then try Connect again."
    )


EXTRACTORS = {
    "battlenet": lambda page, ctx: _extract_battlenet(ctx),
    "nintendo": lambda page, ctx: _extract_nintendo_inline(page, ctx, None),
    "gog": lambda page, ctx: _extract_gog(ctx),
    "psn": lambda page, ctx: _extract_psn(page, ctx),
    "steam": lambda page, ctx: extract_steam(page, ctx),
    "itch": lambda page, ctx: extract_itch(page, ctx),
    "itad": lambda page, ctx: extract_itad(page, ctx),
    "xbox": lambda page, ctx: extract_xbox(page, ctx),
    "xbox_wishlist": lambda page, ctx: _extract_xbox_wishlist_inline(page, ctx, None),
    "nintendo_wishlist": lambda page, ctx: _extract_nintendo_wishlist_inline(page, ctx, None),
    "humble": lambda page, ctx: _extract_humble_inline(page, ctx, None),
    "ubisoft": lambda page, ctx: _extract_ubisoft(page, ctx, None),
    "ea": lambda page, ctx: _extract_ea(page, ctx, None),
    "epic": lambda page, ctx: _extract_epic_inline(page, ctx, None),
    "epic_wishlist": lambda page, ctx: _extract_epic_wishlist_inline(page, ctx, None),
    "amazon_web": lambda page, ctx: _extract_amazon_web(page, ctx, None),
}

# Custom wait/extract loops — not the URL-pattern path in run_browser_auth.
INLINE_PROVIDERS = {
    "psn", "steam", "itch", "itad", "xbox", "xbox_wishlist",
    "ubisoft", "ea", "epic_wishlist", "nintendo", "nintendo_wishlist", "epic",
    "humble", "amazon_web", "battlenet", "gog",
}


def run_browser_auth(provider: str, session: AuthSession) -> dict[str, str] | None:
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
        "xbox": "Click \u201cSign in with Xbox Live\u201d on the xbl.io page, then sign in with your Microsoft account. We'll save your API key automatically once you have it.",
        "xbox_wishlist": (
            "Sign in to xbox.com with your Microsoft account. We'll detect your "
            "wishlist session automatically \u2014 no need to refresh the page."
        ),
        "epic_wishlist": (
            "Sign in if prompted, then stay on store.epicgames.com/wishlist "
            "until your wishlist finishes loading. Clear any Cloudflare check if shown."
        ),
        "ubisoft": (
            "Sign in to Ubisoft and complete 2FA in the browser (use the login popup if it "
            "stays open). Close DevTools if you see a yellow 'Debugger paused' banner."
        ),
        "nintendo": (
            "Sign in to your Nintendo Account. We'll automatically open your eShop "
            "transactions page to capture the session \u2014 no need to navigate yourself."
        ),
        "epic": (
            "Sign in to your Epic account in the browser window. We'll capture and "
            "exchange your authorization code automatically \u2014 no copy/paste needed."
        ),
        "nintendo_wishlist": (
            "Sign in to nintendo.com with your Nintendo Account. We'll detect your "
            "wish list session automatically \u2014 stay on the wish list page until it loads."
        ),
        "humble": (
            "Sign in to Humble Bundle (humblebundle.com). We'll open your library page "
            "to capture the session \u2014 complete any CAPTCHA in the browser window."
        ),
        "ea": (
            "Sign in to your EA account. We'll open the EA deals page to capture your "
            "library token automatically."
        ),
        "amazon_web": (
            "Sign in on the Amazon page in the browser window. After login we'll open "
            "My Collection and save your session automatically."
        ),
        "battlenet": (
            "Sign in at account.battle.net and open your Games list. We'll verify the "
            "library API before saving your session."
        ),
        "gog": (
            "Sign in to your GOG account in the browser window. We'll save your session "
            "automatically once you're logged in."
        ),
    }
    session.emit(
        "waiting_for_user",
        {"message": _CONNECT_HINTS.get(provider, f"Sign in to {spec.label} in the browser window")},
    )

    with launch_persistent_profile(user_data, headless=False) as context:
        context.add_init_script(_STEALTH_INIT)
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
            elif provider == "nintendo_wishlist":
                creds = _extract_nintendo_wishlist_inline(page, context, session)
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
            elif provider == "ubisoft":
                creds = _extract_ubisoft(page, context, session)
            elif provider == "ea":
                creds = _extract_ea(page, context, session)
            elif provider == "nintendo":
                creds = _extract_nintendo_inline(page, context, session)
            elif provider == "epic":
                creds = _extract_epic_inline(page, context, session)
            elif provider == "humble":
                creds = _extract_humble_inline(page, context, session)
            elif provider == "amazon_web":
                creds = _extract_amazon_web(page, context, session)
            elif provider == "battlenet":
                creds = _extract_battlenet_inline(page, context, session)
            elif provider == "gog":
                creds = _extract_gog_inline(page, context, session)
            else:
                page.goto(spec.login_url, wait_until="domcontentloaded")
                session.emit("signed_in", {"url": page.url})
                creds = extractor(page, context)
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
            signed_in = True

        if not signed_in:
            return None

        session.emit("signed_in", {"url": page.url})
        return extractor(page, context)
