"""Headed Chrome/Edge sign-in and credential extraction via CDP."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from auth.api_keys import (
    extract_itad,
    extract_itch,
    extract_steam,
    extract_xbox,
)
from auth.cdp_browser import (
    STEALTH_INIT_SCRIPT,
    ConnectBrowserClosed,
    abort_if_browser_closed,
    auth_banner_init_script,
    is_blank_browser_url,
    launch_persistent_profile,
)
from auth.epic_wishlist_session import EPIC_WISHLIST_URL, epic_store_login_url
from auth.registry import spec_for
from auth.secrets import profile_dir

SUCCESS_WAIT_SEC = 300
POLL_SEC = 0.5
PSN_STORE_URL = "https://store.playstation.com/en-us/"


def _connect_pages(page, context) -> list:
    """Live tabs for a connect session: primary page first, then others."""
    out: list = []
    if page and not page.is_closed:
        out.append(page)
    for pg in context.pages:
        if not pg.is_closed and pg is not page:
            out.append(pg)
    return out or [context.new_page()]


def _drive_connect_page(page, context):
    """Tab the connect loop should observe and navigate.

    CDP may list a preserved ``about:blank`` OAuth popup before the main tab
    finishes loading; ``context.pages[0]`` then looks signed-out/blank while the
    real login URL is on another target (Epic library, Nintendo, etc.).
    """
    for pg in _connect_pages(page, context):
        if not is_blank_browser_url(pg.url or ""):
            return pg
    pages = _connect_pages(page, context)
    return pages[0]


def _wait_for_connect_page(context, *, timeout_s: float = 15.0):
    """Return a live connect page, preferring a non-blank tab when CDP attaches popups."""
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        live = [p for p in context.pages if not p.is_closed]
        if live:
            for pg in live:
                if not is_blank_browser_url(pg.url or ""):
                    return pg
            return live[0]
        try:
            return context.new_page()
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(0.25)
    raise RuntimeError(last_err or "Connect browser has no usable page")
PSN_SSOCOOKIE_URL = "https://ca.account.sony.com/api/v1/ssocookie"
PSN_SSOCOOKIE_INTERVAL_SEC = 10

_STEALTH_INIT = STEALTH_INIT_SCRIPT


class AuthSession:
    __slots__ = ("id", "provider", "fresh_connect", "events", "_listeners", "_finished", "_lock")

    def __init__(self, session_id: str, provider: str, *, fresh_connect: bool = False) -> None:
        self.id = session_id
        self.provider = provider
        self.fresh_connect = fresh_connect
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

BATTLENET_GAMES_URL = "https://account.battle.net/games"


def _extract_battlenet_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Open account.battle.net/games and save cookies only after the library API works."""
    from auth.connect_extractors import battlenet_connect_hint, extract_battlenet_session
    from auth.connect_loop import run_connect_poll

    try:
        page.goto(BATTLENET_GAMES_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    def _on_signed_in(_creds: dict[str, str]) -> None:
        if session:
            session.emit("signed_in", {"url": page.url or BATTLENET_GAMES_URL})

    return run_connect_poll(
        context=context,
        session=session,
        deadline=time.time() + SUCCESS_WAIT_SEC,
        poll_sec=POLL_SEC,
        check=lambda: extract_battlenet_session(context),
        hint=lambda: battlenet_connect_hint(page),
        on_signed_in=_on_signed_in,
        timeout_message=(
            "Could not verify a Battle.net library session — sign in at account.battle.net/games, "
            "wait until your Games list loads, then click Connect again."
        ),
    )


NINTENDO_ACCOUNT_URL = "https://ec.nintendo.com/my/transactions/"
from auth.connect_extractors import (  # noqa: E402
    extract_nintendo_session,
    nintendo_connect_hint,
)


def _extract_nintendo_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Wait for Nintendo sign-in, then auto-navigate to ec.nintendo.com to capture cookies.

    The earlier flow errored with "open ec.nintendo.com after signing in" because
    sign-in lands on accounts.nintendo.com and the eShop cookies aren't set until
    you're back on ec.nintendo.com. We now drive that navigation automatically and
    only fall back to asking the user if it still doesn't land.
    """
    from auth.cdp_browser import browser_session_gone

    try:
        page.goto(NINTENDO_ACCOUNT_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    last_nav = 0.0
    while time.time() < deadline:
        if browser_session_gone(context):
            raise RuntimeError(
                "Sign-in browser window closed before completing. "
                "Click Reconnect to try again."
            )

        drive = _drive_connect_page(page, context)
        url = (drive.url or "").lower()
        signed_in = "ec.nintendo.com" in url and "login" not in url and "connect" not in url

        if signed_in:
            creds = extract_nintendo_session(context)
            if creds:
                return creds

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
                    drive.bring_to_front()
                except Exception:
                    pass
                try:
                    drive.goto(NINTENDO_ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
                except Exception:
                    pass

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            session.emit(
                "waiting_for_user",
                {"message": nintendo_connect_hint(drive, on_account=on_account)},
            )

        page.wait_for_timeout(int(POLL_SEC * 1000))

    creds = extract_nintendo_session(context)
    if creds:
        return creds
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


def _epic_error_from_text(text: str) -> dict[str, str] | None:
    """Detect Epic's corrective-action gate in a redirect body (HTML-wrapped JSON safe)."""
    from clients.epic_client import corrective_action_in_text

    return corrective_action_in_text(text or "")


EPIC_CORRECTIVE_ACTION_HINT = (
    "Epic needs you to accept its privacy policy. Accept the privacy policy / "
    "complete the prompt in the sign-in window, then we'll finish connecting "
    "automatically."
)
EPIC_CORRECTIVE_ACTION_ERROR = (
    "Epic needs you to accept its privacy policy. In the Epic sign-in window, "
    "accept the privacy policy / complete the prompt, then refresh the page and "
    "click Connect again."
)


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
        drive = _drive_connect_page(page, context)

        redirect_page = None
        for pg in _connect_pages(page, context):
            if EPIC_REDIRECT_MARKER in (pg.url or "").lower():
                redirect_page = pg
                break
        if redirect_page is not None:
            main = redirect_page
            url = (main.url or "").lower()
            body = ""
            try:
                body = main.evaluate("() => document.body ? document.body.innerText : ''") or ""
            except Exception:
                body = ""
            code = _epic_code_from_text(body)
            html = ""
            if not code:
                try:
                    html = main.content()
                except Exception:
                    html = ""
                code = _epic_code_from_text(html)
            if code:
                from clients.epic_client import (
                    EpicAuthError,
                    EpicClient,
                    EpicCorrectiveActionError,
                    default_epic_cache_dir,
                )

                try:
                    EpicClient(auth_code=code, cache_dir=default_epic_cache_dir()).login()
                except EpicCorrectiveActionError as exc:
                    raise RuntimeError(EPIC_CORRECTIVE_ACTION_ERROR) from exc
                except EpicAuthError as exc:
                    raise RuntimeError(
                        f"Epic rejected the captured code ({exc}). Refresh the Epic page so a new "
                        "code appears, or paste the authorizationCode into the fallback field below."
                    ) from exc
                return {"EPIC_AUTH_CODE": code}

            # No code yet: if Epic is showing its corrective-action gate (e.g.
            # privacy-policy acceptance), guide the user to complete it and keep
            # polling instead of silently timing out.
            if _epic_error_from_text(body) or _epic_error_from_text(html):
                now = time.time()
                if session and now - last_hint > 8:
                    last_hint = now
                    session.emit("waiting_for_user", {"message": EPIC_CORRECTIVE_ACTION_HINT})
                page.wait_for_timeout(int(POLL_SEC * 1000))
                continue

        url = (drive.url or "").lower()
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
    from auth.connect_extractors import pick_gog_al_from_cookies as _pick

    return _pick(cookies)


def _extract_gog_inline(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Poll for gog-al after the user signs in — do not trust the /en homepage URL."""
    from auth.connect_extractors import extract_gog_session, gog_connect_hint
    from auth.connect_loop import run_connect_poll

    try:
        page.goto("https://www.gog.com/", wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    def _on_signed_in(creds: dict[str, str]) -> None:
        if session:
            session.emit("signed_in", {"url": page.url or "https://www.gog.com/"})

    return run_connect_poll(
        context=context,
        session=session,
        deadline=time.time() + SUCCESS_WAIT_SEC,
        poll_sec=POLL_SEC,
        check=lambda: extract_gog_session(context),
        hint=lambda: gog_connect_hint(page),
        on_signed_in=_on_signed_in,
        timeout_message=(
            "Could not capture a GOG session in time — sign in at gog.com in the browser window, "
            "then click Connect again."
        ),
    )


def _psn_cookie(context) -> str:
    for c in context.cookies():
        if c.get("name") == "npsso" and c.get("value"):
            return c["value"]
    return ""


PSN_CHECK_VALID = "valid"
PSN_CHECK_INVALID = "invalid"
PSN_CHECK_UNREACHABLE = "unreachable"


def _check_npsso(npsso: str) -> str:
    """Tri-state NPSSO probe: valid / invalid / unreachable.

    A PsnAuthError means PSN positively rejected the token (invalid/private).
    Any other exception (no connection, timeout, unexpected upstream error) is
    a transient failure we report as ``unreachable`` so the connect loop keeps
    polling instead of permanently discarding a token that may be fine.
    """
    try:
        from clients.psn_client import PsnAuthError, validate_npsso
    except Exception:  # noqa: BLE001
        return PSN_CHECK_UNREACHABLE
    try:
        validate_npsso(npsso)
        return PSN_CHECK_VALID
    except PsnAuthError:
        return PSN_CHECK_INVALID
    except Exception:  # noqa: BLE001 — network/transport blip, not a rejected token
        return PSN_CHECK_UNREACHABLE


def _validate_npsso(npsso: str) -> bool:
    return _check_npsso(npsso) == PSN_CHECK_VALID


def _psn_on_blocked_account_page(url: str, body: str) -> bool:
    u = (url or "").lower()
    b = (body or "").lower()
    if "global_error" in u:
        return True
    if "sonyacct/signin" in u or "my.account.sony.com" in u:
        if "something went wrong" in b or "global_error" in u:
            return True
    return False


def _fetch_npsso_via_ssocookie(page) -> str:
    """Fetch npsso from Sony's ssocookie endpoint (browser session must be signed in)."""
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
    return ""


def _fetch_npsso_background(page, context) -> tuple[str, str]:
    """Return ``(token, source)`` where source is ``ssocookie``, ``cookie``, or ``""``.

    Sony's ssocookie endpoint is the source of truth after sign-in. The browser
    cookie jar can keep a stale npsso from a prior session and must not win.
    """
    via_api = _fetch_npsso_via_ssocookie(page)
    cookie_jar = _psn_cookie(context)
    if via_api:
        return via_api, "ssocookie"
    if cookie_jar:
        return cookie_jar, "cookie"
    return "", ""


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
            fresh, _source = _fetch_npsso_background(page, context)
            if fresh and fresh not in tried_cookie:
                result = _check_npsso(fresh)
                if result == PSN_CHECK_VALID:
                    return {"PSN_NPSSO": fresh}
                # Only blacklist a token PSN positively rejected — an
                # "unreachable" result is a network blip, so keep retrying it.
                if result == PSN_CHECK_INVALID:
                    tried_cookie.add(fresh)

        # Also try the cookie directly (cheap)
        cookie_val = _psn_cookie(context)
        if cookie_val and cookie_val not in tried_cookie:
            result = _check_npsso(cookie_val)
            if result == PSN_CHECK_VALID:
                return {"PSN_NPSSO": cookie_val}
            if result == PSN_CHECK_INVALID:
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


def _epic_on_wishlist(url: str) -> bool:
    ul = (url or "").lower()
    return "store.epicgames.com" in ul and "wishlist" in ul


def _epic_on_login_page(url: str) -> bool:
    ul = (url or "").lower()
    return "id.epicgames.com" in ul or "/id/login" in ul


def _extract_epic_wishlist_inline(page, context, session) -> dict[str, str]:
    """Drive Epic storefront sign-in, wait for wishlist data, return profile marker.

    The saved browser profile (cache/auth/profiles/epic_wishlist) is reused by
    fetch_epic_wishlist.py. Connect completes when wishlistItems is present in
    either a GraphQL response or Epic's dehydrated React Query HTML state.
    """
    from auth.connect_extractors import build_epic_wishlist_graphql_sniffer
    from auth.epic_wishlist_session import (
        storefront_bounced_to_home,
        wishlist_capture_complete_from_html,
    )

    sniffer = build_epic_wishlist_graphql_sniffer()
    wishlist_loaded = False
    saw_id_login = False
    did_post_login_nav = False

    try:
        _debug_path = profile_dir("epic_wishlist").parent / "epic_wishlist_connect_debug.json"
    except Exception:  # noqa: BLE001
        _debug_path = None

    def _write_debug() -> None:
        if _debug_path is None or not sniffer.debug_log:
            return
        try:
            _debug_path.parent.mkdir(parents=True, exist_ok=True)
            _debug_path.write_text(
                json.dumps(sniffer.debug_log[:50], indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    sniffer.attach(page)
    try:
        page.goto(epic_store_login_url(), wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        if not wishlist_loaded and sniffer.drain():
            wishlist_loaded = True
            _write_debug()
        url = page.url or ""
        ul = url.lower()
        on_wishlist = _epic_on_wishlist(url)
        if not wishlist_loaded and on_wishlist:
            try:
                if wishlist_capture_complete_from_html(page.content()):
                    wishlist_loaded = True
            except Exception:  # noqa: BLE001
                pass
        if _epic_on_login_page(url):
            saw_id_login = True
        if (
            not wishlist_loaded
            and not did_post_login_nav
            and saw_id_login
            and storefront_bounced_to_home(url)
        ):
            did_post_login_nav = True
            try:
                page.goto(EPIC_WISHLIST_URL, wait_until="domcontentloaded", timeout=25_000)
            except Exception:  # noqa: BLE001
                pass
            if not wishlist_loaded and sniffer.drain():
                wishlist_loaded = True
                _write_debug()
        if wishlist_loaded:
            try:
                page.wait_for_timeout(800)
            except Exception:  # noqa: BLE001
                pass
            return {"EPIC_STORE_COOKIE": "ready"}

        now = time.time()

        if session and now - last_msg > 8:
            last_msg = now
            if "challenge" in ul or "cloudflare" in ul:
                msg = "Cloudflare challenge — click the checkbox if shown."
            elif _epic_on_login_page(url) or "signin" in ul:
                msg = (
                    "Sign in to Epic in this window — you'll be returned to your "
                    "wishlist automatically. Clear any Cloudflare check if shown."
                )
            elif on_wishlist:
                msg = "On the wishlist page? Give it a moment to load."
            elif "store.epicgames.com" in ul:
                msg = (
                    "Signed in? Opening your wishlist — give it a moment to load."
                )
            else:
                msg = (
                    "Sign in to Epic in this window — you'll be returned to your "
                    "wishlist automatically."
                )
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect Epic wishlist sign-in — sign in at store.epicgames.com/wishlist, "
        "clear any Cloudflare challenge, and let your wishlist finish loading."
    )


XBOX_WISHLIST_URL = "https://www.xbox.com/en-us/wishlist"
XBOX_WISHLIST_POLL_SEC = 2.5

_XBOX_WISHLIST_DOM_PROBE = """() => {
  const out = {host:'', path:'', hasState:false, isSignedIn:null, btnCount:0,
              matchTexts:[], onAuth:false, err:null};
  try {
    const loc = window.location;
    out.host = (loc.hostname || '').toLowerCase();
    out.path = (loc.pathname || '').toLowerCase();
    out.onAuth = out.path.includes('/auth/msa');
    const st = window.__PRELOADED_STATE__;
    out.hasState = !!st;
    if (st && st.user) out.isSignedIn = !!st.user.isSignedIn;
    const els = Array.from(document.querySelectorAll('button, a[role="button"], a'));
    const re = /\\b(buy|details|pre-order|preorder)\\b/i;
    for (const el of els) {
      const t = (el.textContent || '').trim();
      if (re.test(t)) { out.matchTexts.push(t.slice(0, 24)); }
    }
    out.btnCount = out.matchTexts.length;
  } catch (e) { out.err = String(e); }
  return JSON.stringify(out);
}"""


def _xbox_url_on_wishlist(url: str) -> bool:
    """True only when the navigated path is xbox.com/wishlist (not redirect_uri)."""
    try:
        parsed = urlparse(url or "")
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower()
    if host != "xbox.com" and not host.endswith(".xbox.com"):
        return False
    return "/wishlist" in (parsed.path or "").lower()


def _xbox_url_is_login(url: str) -> bool:
    u = (url or "").lower()
    if _xbox_url_on_wishlist(url):
        return False
    return (
        "login.live.com" in u
        or "login.microsoftonline" in u
        or "account.microsoft" in u
        or ("signin" in u and "xbox.com" not in u)
    )


def _xbox_wishlist_dom_diag(page) -> dict | None:
    """Return DOM diagnostics for the wishlist tab (or ``None`` on failure)."""
    if page is None:
        return {"diag_err": "page_none"}
    try:
        if not _xbox_url_on_wishlist(page.url or ""):
            return {"diag_err": "not_wishlist", "url": (page.url or "")[:80]}
        raw = page.evaluate(_XBOX_WISHLIST_DOM_PROBE, timeout=5)
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
        return {"diag_err": "bad_type", "raw_type": type(raw).__name__}
    except Exception as exc:  # noqa: BLE001
        return {"diag_err": "evaluate_threw", "exc": str(exc)[:120]}


def _xbox_wishlist_dom_signed_in(page) -> bool:
    """Detect a hydrated wishlist when SSR still says signed-out after fresh OAuth.

    Signed-in evidence: ``__PRELOADED_STATE__.user.isSignedIn`` true, or the
    rendered list shows purchase actions (BUY / DETAILS / PRE-ORDER). A
    signed-out wishlist redirects to ``/auth/msa`` and never renders these.
    """
    diag = _xbox_wishlist_dom_diag(page)
    if not diag:
        return False
    if diag.get("onAuth"):
        return False
    if diag.get("isSignedIn") is True:
        return True
    return bool(diag.get("btnCount"))


def _xbox_any_wishlist_dom_signed_in(context) -> tuple[bool, Any]:
    """Scan every live tab for a hydrated signed-in wishlist."""
    for pg in context.pages:
        if pg.is_closed:
            continue
        if _xbox_url_on_wishlist(pg.url or "") and _xbox_wishlist_dom_signed_in(pg):
            return True, pg
    return False, None


def _xbox_has_msa_session(context) -> bool:
    """True when Microsoft/Xbox auth cookies are present in the profile."""
    try:
        names = {c.get("name", "") for c in context.cookies()}
    except Exception:  # noqa: BLE001
        return False
    return "WLSSC" in names or any(n.startswith("XBXXtk") for n in names)


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


def _xbox_signed_in_state_from_html(html: str) -> dict | None:
    state = _parse_xbox_preloaded_state(html)
    if not state:
        return None
    user = state.get("user") or {}
    if not user.get("isSignedIn"):
        return None
    page_meta = (state.get("pageRequestMetadata") or {}).get("/wishlist") or {}
    err = page_meta.get("error") or {}
    if err.get("httpStatusCode") == 403:
        return None
    return state


def _xbox_signed_in_state(context, page=None) -> dict | None:
    """Return parsed wishlist SSR when signed in (else ``None``).

    Prefer the live page document after ``page.goto`` — but stale client-side
    SSR can show signed-out even when cookies are valid, and the /auth/msa
    handoff page always looks signed-out. Fall through to cookie-based HTTP GET
    when the page document does not confirm a signed-in wishlist session.
    After a fresh MSA sign-in the SPA can hydrate the wishlist while SSR still
    says signed-out; scan every live wishlist tab and accept DOM evidence.
    """
    pages: list = []
    if page is not None and not page.is_closed:
        pages.append(page)
    for pg in context.pages:
        if not pg.is_closed and pg not in pages and _xbox_url_on_wishlist(pg.url or ""):
            pages.append(pg)

    for pg in pages:
        try:
            url = pg.url or ""
            if _xbox_url_on_wishlist(url):
                state = _xbox_signed_in_state_from_html(pg.content())
                if state:
                    return state
                if _xbox_wishlist_dom_signed_in(pg):
                    return {"user": {"isSignedIn": True}, "_source": "dom"}
        except Exception:  # noqa: BLE001
            pass
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
    return _xbox_signed_in_state_from_html(html)


def _xbox_capture_wishlist_api(page, sniffer, *, timeout_s: float = 12.0) -> None:
    """After sign-in, linger on the wishlist so the Emerald XHR fires and is sniffed."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if sniffer.token:
            return
        page.wait_for_timeout(500)


def _xbox_wishlist_connect_creds(sniffer) -> dict[str, str]:
    creds = {"XBOX_WISHLIST_PROFILE": "ready"}
    creds.update(sniffer.creds())
    return creds


def _extract_xbox_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open xbox.com/wishlist, wait for MSA sign-in (detected via SSR HTML),
    then capture the Emerald wishlist API token for headless replay. The
    persistent profile remains the fallback credential.
    """
    from auth.xbox_wishlist_capture import WishlistApiSniffer


    sniffer = WishlistApiSniffer()
    _sniffer_pages: set[int] = set()

    def _attach_sniffer(pg) -> None:
        """Bind the Emerald sniffer to every live tab. After a fresh MSA sign-in
        the wishlist (where the XHR fires) loads in a different tab than the one
        the connect loop started from, so attaching only to ``page`` misses the
        token entirely."""
        try:
            key = id(pg)
            if key not in _sniffer_pages:
                pg.on("response", sniffer.on_response)
                _sniffer_pages.add(key)
        except Exception:  # noqa: BLE001
            pass

    def _xbox_active_page():
        """Pick the tab actually on the wishlist; never the /auth/msa handoff or
        the login.live popup. CDP often lists the handoff tab as ``pages[0]``
        after sign-in, which strands a loop that blindly polls ``page``."""
        live = [pg for pg in context.pages if not pg.is_closed]
        for pg in live:
            if _xbox_url_on_wishlist(pg.url or ""):
                return pg
        for pg in live:
            u = (pg.url or "").lower()
            if "xbox.com" in u and "/auth/msa" not in u and "action=loggedin" not in u:
                return pg
        return _drive_connect_page(page, context)

    _attach_sniffer(page)

    try:
        page.goto(XBOX_WISHLIST_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:  # noqa: BLE001
        pass


    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    last_ssr_refresh = 0.0
    while time.time() < deadline:
        for pg in context.pages:
            if not pg.is_closed:
                _attach_sniffer(pg)
        active = _xbox_active_page()
        url = active.url or ""
        url_low = url.lower()
        on_login = _xbox_url_is_login(url)
        # MSA hands the session back via xbox.com/auth/msa. Two distinct phases:
        #   - MID-EXCHANGE (action=login / #code= / oauth20): the SPA is still
        #     setting cookies; navigating away aborts it, so we must wait.
        #   - HANDOFF DONE (action=loggedin): the cookie exchange is COMPLETE.
        #     In this headed CDP context the SPA does not always auto-redirect
        #     to /wishlist, so the loop would otherwise sit on the handoff page
        #     forever (Emerald XHR never fires, SSR here is signed-out). Once
        #     done, drive the tab to /wishlist to trigger the wishlist session.
        handoff_done = "action=loggedin" in url_low
        mid_exchange = not handoff_done and (
            ("/auth/msa" in url_low and "action=login" in url_low)
            or "#code=" in url_low
            or ("oauth20" in url_low and _xbox_url_is_login(url))
        )
        on_handoff = handoff_done or mid_exchange or "/auth/msa" in url_low
        on_wishlist = _xbox_url_on_wishlist(url)
        dom_signed_in_any, dom_page = _xbox_any_wishlist_dom_signed_in(context)
        dom_signed_in = dom_signed_in_any
        token_ready = bool(sniffer.token)
        if token_ready and dom_signed_in_any and not on_login:
            if session:
                session.emit(
                    "waiting_for_user",
                    {"message": "Signed in \u2014 capturing your wishlist session..."},
                )
            sniffer.dump()
            return _xbox_wishlist_connect_creds(sniffer)
        # Cookie exchange complete (action=loggedin) but the SPA stalled on the
        # handoff page: drive forward to /wishlist so the Emerald wishlist XHR
        # fires. Wait through mid-exchange; never navigate during it.
        if handoff_done and not on_wishlist:
            now = time.time()
            if now - last_ssr_refresh >= 3.0:
                last_ssr_refresh = now
                try:
                    # commit: do not wait for the heavy SPA readyState probe — that
                    # can block 15s+ while the user already sees the wishlist.
                    active.goto(XBOX_WISHLIST_URL, wait_until="commit", timeout=15000)
                    active.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    pass
                continue
        # xbox.com bakes __PRELOADED_STATE__ into the HTML at load time and
        # never refreshes it client-side. After MSA sign-in we may need one
        # refresh to pull SSR that reflects the new cookies — but once the user
        # is on /wishlist, stop hammering reloads or the Emerald API never fires.
        elif not on_login and not on_handoff and "xbox.com" in url_low:
            now = time.time()
            need_refresh = not on_wishlist or (
                not token_ready
                and not dom_signed_in
                and now - last_ssr_refresh >= 8.0
            )
            if need_refresh:
                last_ssr_refresh = now
                try:
                    active.goto(XBOX_WISHLIST_URL, wait_until="commit", timeout=15000)
                    active.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    pass

        # During MSA OAuth the active tab navigates constantly — page.content()
        # and the cookie-based HTTP GET can block for 20s+ and stall the loop.
        state = None
        if not on_login and not mid_exchange:
            state = _xbox_signed_in_state(context, dom_page or active)
        token_ready = bool(sniffer.token)
        dom_signed_in_any, dom_page = _xbox_any_wishlist_dom_signed_in(context)
        dom_signed_in = dom_signed_in_any
        msa_ready = _xbox_has_msa_session(context)
        if token_ready and dom_signed_in_any and not on_login:
            if session:
                session.emit(
                    "waiting_for_user",
                    {"message": "Signed in \u2014 capturing your wishlist session..."},
                )
            sniffer.dump()
            return _xbox_wishlist_connect_creds(sniffer)
        if state is not None or (dom_signed_in_any and msa_ready and not on_login):
            if session:
                session.emit(
                    "waiting_for_user",
                    {"message": "Signed in \u2014 capturing your wishlist session..."},
                )
            _xbox_capture_wishlist_api(dom_page or active, sniffer)
            sniffer.dump()
            return _xbox_wishlist_connect_creds(sniffer)

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            if on_login:
                msg = "Sign in to your Microsoft account in the browser window."
            elif "xbox.com" not in url_low:
                msg = "Open xbox.com/wishlist after signing in."
            else:
                msg = "Signed in \u2014 waiting for xbox.com to issue your wishlist session."
            session.emit("waiting_for_user", {"message": msg})

        active.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect an Xbox sign-in \u2014 sign in to xbox.com/wishlist "
        "and keep the window open until it closes."
    )


NINTENDO_WISHLIST_URL = "https://www.nintendo.com/us/wish-list/"
NINTENDO_WISHLIST_POLL_SEC = 2.5


def _nintendo_wishlist_session_ready(html: str, url: str, api_payloads: list[Any]) -> bool:
    """True when storefront GraphQL confirms a signed-in wish-list session."""
    from fetchers.fetch_nintendo_wishlist import _wishlist_graphql_ok, parse_wishlist_sources

    u = (url or "").lower()
    if "accounts.nintendo.com/login" in u:
        return False
    if any(_wishlist_graphql_ok(p) for p in api_payloads):
        return True
    return bool(parse_wishlist_sources(html, api_payloads))


def _extract_nintendo_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open nintendo.com/us/wish-list/, wait for sign-in, return marker cred."""
    from fetchers.fetch_nintendo_wishlist import (
        _drain_nintendo_candidates,
        _is_nintendo_graphql_url,
    )

    candidates: list[Any] = []

    def _stash_graphql(response) -> None:
        try:
            if response.status >= 400:
                return
            if not _is_nintendo_graphql_url(response.url or ""):
                return
            ct = (response.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            candidates.append(response)
        except Exception:  # noqa: BLE001
            pass

    page.on("response", _stash_graphql)
    try:
        page.goto(NINTENDO_WISHLIST_URL, wait_until="commit", timeout=20000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        api_payloads = _drain_nintendo_candidates(candidates)
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            html = ""
        url = page.url or ""
        if _nintendo_wishlist_session_ready(html, url, api_payloads):
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
    """True when the orders API accepts the profile (stale cookies alone are not enough)."""
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
    from auth.connect_extractors import extract_humble_session, humble_connect_hint
    from auth.connect_loop import run_connect_poll

    try:
        page.goto(HUMBLE_LIBRARY_URL, wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    return run_connect_poll(
        context=context,
        session=session,
        deadline=time.time() + SUCCESS_WAIT_SEC,
        poll_sec=HUMBLE_POLL_SEC,
        check=lambda: extract_humble_session(context, page),
        hint=lambda: humble_connect_hint(page),
        timeout_message=(
            "Could not detect a Humble sign-in - sign in at humblebundle.com/home/library "
            "and keep the window open until it closes."
        ),
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
    from auth.connect_extractors import (
        build_ubisoft_header_sniffer,
        extract_ubisoft_session,
        ubisoft_connect_hint,
        ubisoft_session_captured,
    )

    sniffer = build_ubisoft_header_sniffer()
    sniffer.attach(context)
    try:
        page.goto("https://www.ubisoft.com/en-us/ubisoft-connect", wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    seen_success = False
    nudged = 0
    while time.time() < deadline:
        creds = extract_ubisoft_session(sniffer)
        if creds:
            return creds

        live = [pg for pg in context.pages if not pg.is_closed]
        main = _ubisoft_active_page(live) or (live[0] if live else context.new_page())
        urls = [(pg.url or "").lower() for pg in live]
        if len(live) > 1:
            main_url = (main.url or "").lower()
            if "connect.ubisoft.com/login" in main_url or UBISOFT_SUCCESS_URL in main_url:
                try:
                    main.bring_to_front()
                except Exception:
                    pass
        on_success = any(UBISOFT_SUCCESS_URL in u for u in urls)

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
            msg = ubisoft_connect_hint(
                urls=urls,
                seen_success=seen_success,
                captured=ubisoft_session_captured(sniffer),
            )
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Ubisoft API headers not captured — sign in at ubisoft.com, complete 2FA, and open your "
        "games library. If a verify step left a blank tab, close it and click Connect again."
    )


def _extract_ea(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Confirm ea.com login via in-browser Juno GraphQL (and legacy Bearer when present)."""
    from clients.ea_session import (
        EA_COOKIE_SESSION,
        EA_DEALS_URL,
        EA_GRAPHQL_HOST,
        EA_LOGIN_URL,
        _ensure_ea_deals_ready,
        _merge_owned_items,
        drain_ea_graphql_hook,
        ensure_ea_graphql_hook,
        fetch_owned_games_inpage,
        fetch_owned_games_playwright_request,
        install_ea_graphql_hook,
        is_ea_session_expired_page,
        normalize_bearer,
        probe_ea_token,
        write_ea_connect_snapshot,
    )

    install_ea_graphql_hook(context)
    ensure_ea_graphql_hook(page)

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
        page.goto(EA_LOGIN_URL, wait_until="commit", timeout=25_000)
    except Exception:
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_hint = 0.0
    nudged = False
    redirected_expired = False
    saw_signin = False
    require_signin = bool(getattr(session, "fresh_connect", False)) if session else False
    consecutive_auth = 0
    owned_accum: list[dict] = []
    owned_seen: set[str] = set()
    last_poll_log = 0.0

    def _login_witnessed() -> bool:
        return saw_signin or not require_signin

    while time.time() < deadline:
        abort_if_browser_closed(context)

        cookies = context.cookies()

        auth_ok, owned_batch, hook_stats = drain_ea_graphql_hook(page)
        _merge_owned_items(owned_accum, owned_seen, owned_batch)

        # Mixed deals-page traffic often includes both authenticated `me` rows and
        # unauthenticated errors in one drain ΓÇö prefer auth_ok for this poll.
        if auth_ok:
            consecutive_auth += 1
        elif hook_stats.get("hook_unauthenticated"):
            consecutive_auth = 0
        else:
            consecutive_auth = 0

        now = time.time()
        if now - last_poll_log >= 2.0:
            last_poll_log = now

        hook_entries = int(hook_stats.get("hook_entries") or 0)
        deals_burst_ok = (
            nudged
            and hook_entries >= 1
            and bool(hook_stats.get("hook_authenticated"))
        )
        sustained_cookie = auth_ok and _login_witnessed() and (
            consecutive_auth >= 2 or bool(owned_accum) or deals_burst_ok
        )
        if sustained_cookie:
            if deals_burst_ok and not owned_accum:
                for _ in range(4):
                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        break
                    ensure_ea_graphql_hook(page)
                    _auth_ok, owned_batch, _stats = drain_ea_graphql_hook(page)
                    _merge_owned_items(owned_accum, owned_seen, owned_batch)
                    if owned_accum:
                        break
            if not owned_accum and deals_burst_ok:
                try:
                    _ensure_ea_deals_ready(page, dwell_ms=1500)
                    pw_owned = fetch_owned_games_playwright_request(context)
                    _merge_owned_items(owned_accum, owned_seen, pw_owned)
                except Exception:  # noqa: BLE001
                    pass
            if not owned_accum and deals_burst_ok:
                try:
                    _ensure_ea_deals_ready(page, dwell_ms=1500)
                    inpage_owned = fetch_owned_games_inpage(page)
                    _merge_owned_items(owned_accum, owned_seen, inpage_owned)
                except Exception:  # noqa: BLE001
                    pass
            if not owned_accum:
                cookie_jar = context.cookies()
                bearer = (saw_token.get("value") or "").strip() if saw_token.get("ok") else ""
                for mode, token in (
                    ("bearer+cookies", bearer),
                    ("cookies", ""),
                ):
                    if mode == "bearer+cookies" and not token:
                        continue
                    try:
                        from clients.ea_client import EaClient

                        client = EaClient(token, cookies=cookie_jar) if token else EaClient(cookies=cookie_jar)
                        api_owned = client.get_owned_games()
                        _merge_owned_items(owned_accum, owned_seen, api_owned)
                        if owned_accum:
                            break
                    except Exception:  # noqa: BLE001
                        pass
            if not owned_accum:
                for attempt in range(3):
                    try:
                        _ensure_ea_deals_ready(page, dwell_ms=1500 + attempt * 1000)
                        inpage_owned = fetch_owned_games_inpage(page)
                        _merge_owned_items(owned_accum, owned_seen, inpage_owned)
                        if owned_accum:
                            break
                    except Exception:  # noqa: BLE001
                        pass
            cookie_jar = context.cookies()
            write_ea_connect_snapshot(
                owned_accum,
                browser_auth_ok=True,
                cookies=cookie_jar,
            )
            return {
                "EA_PROFILE": "ready",
                "EA_BEARER_TOKEN": EA_COOKIE_SESSION,
            }

        if saw_token["ok"] and saw_token["value"] and _login_witnessed():
            probe = probe_ea_token(saw_token["value"], cookies)
            # APQ-owned-games miss falls back to subscription probe only ΓÇö that
            # bearer still fails fetch_ea; wait for sustained cookie handoff.
            if probe.get("ok") and not probe.get("library_via_browser"):
                return {
                    "EA_PROFILE": "ready",
                    "EA_BEARER_TOKEN": saw_token["value"],
                }
            saw_token["ok"] = False
            saw_token["value"] = ""

        url = (page.url or "").lower()
        if "signin.ea.com" in url:
            saw_signin = True
        signed_in = "ea.com" in url and "login" not in url and "signin.ea.com" not in url
        expired_page = False
        try:
            expired_page = is_ea_session_expired_page(page.content(), page.url or "")
        except Exception:
            expired_page = False

        if signed_in and not nudged:
            if require_signin and not saw_signin:
                try:
                    page.goto(EA_LOGIN_URL, wait_until="commit", timeout=25_000)
                    ensure_ea_graphql_hook(page)
                except Exception:
                    pass
            else:
                nudged = True
                if session:
                    session.emit("signed_in", {"url": page.url or EA_LOGIN_URL})
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                try:
                    page.goto(EA_DEALS_URL, wait_until="commit", timeout=25_000)
                    ensure_ea_graphql_hook(page)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
        elif expired_page and not redirected_expired:
            redirected_expired = True
            ensure_ea_graphql_hook(page)
            try:
                page.goto(EA_LOGIN_URL, wait_until="commit", timeout=25_000)
            except Exception:
                pass
        elif signed_in and nudged:
            ensure_ea_graphql_hook(page)

        now = time.time()
        if session and now - last_hint > 10:
            last_hint = now
            if "signin.ea.com" in url or "/login" in url:
                msg = "Sign in to your EA account in the browser window."
            elif expired_page:
                msg = "EA session expired ΓÇö sign in again in the browser window."
            elif signed_in:
                msg = "Signed in ΓÇö confirming your EA session on the deals page."
            else:
                msg = "Keep the window open while we confirm your EA App session."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "EA session not confirmed ΓÇö sign in at ea.com and wait for the deals page "
        "to finish loading before the window closes."
    )


def _extract_amazon_web(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Confirm Prime Gaming session; durable credential is the saved browser profile."""
    from clients.amazon_web_client import (
        COLLECTION_URLS,
        _capture_claims_from_response,
        _poll_prime_collection,
        filter_codeless_claims,
        raw_dump_path,
        scrub_claim_codes,
    )

    raw_claims: list[dict[str, Any]] = []
    captured: dict[str, bool] = {
        "done": False,
        "claims_captured": False,
        "session_only_captured": False,
    }
    candidates: list[Any] = []

    def on_response(resp: Any) -> None:
        _capture_claims_from_response(resp, candidates, raw_claims, captured)

    page.on("response", on_response)
    _poll_prime_collection(
        page,
        context,
        deadline=time.time() + SUCCESS_WAIT_SEC,
        candidates=candidates,
        raw_claims=raw_claims,
        captured=captured,
        allow_session_only=True,
        start_at_signin=True,
        session=session,
        poll_interval_ms=int(POLL_SEC * 1000),
        session_only_grace_s=2.0,
    )

    if captured["done"]:
        # If we successfully captured the claims payload (even an empty list),
        # persist it for the later headless fetcher as a fallback.
        if captured.get("claims_captured"):
            path = raw_dump_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Strip one-time redemption/activation codes before persisting: the
            # raw dump is a plaintext fallback for the headless fetcher and must
            # never store claim credentials.
            safe_claims = scrub_claim_codes(raw_claims)
            path.write_text(
                json.dumps(
                    {
                        "urls": list(COLLECTION_URLS),
                        "raw_claim_count": len(safe_claims),
                        "raw_claims": safe_claims,
                        "codeless_count": len(filter_codeless_claims(safe_claims)),
                        "capture_reason": "headed_connect",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return {"AMAZON_WEB_PROFILE": "ready"}

    raise RuntimeError(
        "Prime Gaming session not confirmed — sign in on the Amazon page, wait for "
        "My Collection (or gaming.amazon.com) to load, then try Connect again."
    )


# Every browser/oauth provider is handled by a dedicated inline wait/extract
# loop in run_browser_auth (below). This set is the authoritative whitelist of
# supported providers — run_browser_auth rejects anything not listed here.
INLINE_PROVIDERS = {
    "psn", "steam", "itch", "itad", "xbox", "xbox_wishlist",
    "ubisoft", "ea", "epic_wishlist", "nintendo", "nintendo_wishlist", "epic",
    "humble", "amazon_web", "battlenet", "gog",
}


def run_browser_auth(provider: str, session: AuthSession) -> dict[str, str] | None:
    spec = spec_for(provider)
    if provider not in INLINE_PROVIDERS:
        raise RuntimeError(f"No browser extractor for {provider}")

    user_data = str(profile_dir(provider))
    _CONNECT_HINTS = {
        "psn": "Sign in to PlayStation Store (Sign In, top-right). Keep this window open.",
        "steam": "Sign in to Steam. We'll save your API key automatically.",
        "itch": "Sign in to itch.io. We'll save your API key automatically.",
        "itad": "Sign in to IsThereAnyDeal. We'll register an app and save your API key.",
        "xbox": (
            "Click \u201cSign in with Xbox Live\u201d on the xbl.io page, then sign in with your "
            "Microsoft account. We'll save your API key automatically once you have it."
        ),
        "xbox_wishlist": (
            "Sign in to xbox.com with your Microsoft account. We'll detect your "
            "wishlist session automatically \u2014 no need to refresh the page."
        ),
        "epic_wishlist": (
            "Sign in to Epic in this window — you'll be returned to your wishlist "
            "automatically. Clear any Cloudflare check if shown, and keep this "
            "window open until your wishlist finishes loading."
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
    connect_hint = _CONNECT_HINTS.get(
        provider,
        f"Sign in to {spec.label} in the browser window, then keep it open until it closes automatically.",
    )
    session.emit("waiting_for_user", {"message": connect_hint})

    from auth.cdp_browser import release_chromium_profile_lock

    release_chromium_profile_lock(user_data)

    with launch_persistent_profile(
        user_data,
        headless=False,
        initial_url=spec.login_url if provider == "ea" else None,
    ) as context:
        try:
            context.add_init_script(_STEALTH_INIT)
            # Paint a persistent, click-through banner inside the popup so users see
            # the same guidance there (not just on the dashboard). Keep it in sync
            # with the live waiting_for_user / signed_in messages.
            context.add_init_script(auth_banner_init_script(connect_hint))

            def _sync_auth_banner(event: str, data: dict) -> None:
                if event == "waiting_for_user":
                    context.set_auth_banner((data or {}).get("message") or connect_hint)
                elif event == "signed_in":
                    context.set_auth_banner(
                        "Signed in \u2014 keep this window open until it closes automatically."
                    )

            session.add_listener(_sync_auth_banner)
            page = _wait_for_connect_page(context)
            page = _drive_connect_page(page, context)

            # Raise the connect window to the OS foreground — on Windows it often
            # opens behind the dashboard/IDE, and Page.bringToFront alone only swaps
            # the active tab without focusing the window.
            try:
                page.focus_window()
            except Exception:
                pass

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
                else:  # pragma: no cover — gate above guarantees an inline provider
                    raise RuntimeError(f"No inline handler for {provider}")
                return creds
        except ConnectBrowserClosed:
            return None
