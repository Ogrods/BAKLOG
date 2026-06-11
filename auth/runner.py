"""Headed Chrome/Edge sign-in and credential extraction via CDP."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from auth.api_keys import (
    extract_itad,
    extract_itch,
    extract_steam,
    extract_xbox,
)
from auth.cdp_browser import (
    STEALTH_INIT_SCRIPT,
    auth_banner_init_script,
    launch_persistent_profile,
)
from auth.epic_wishlist_session import EPIC_WISHLIST_URL, epic_store_login_url
from auth.registry import spec_for
from auth.secrets import profile_dir

SUCCESS_WAIT_SEC = 300
POLL_SEC = 0.5
PSN_STORE_URL = "https://store.playstation.com/en-us/"
PSN_SSOCOOKIE_URL = "https://ca.account.sony.com/api/v1/ssocookie"
PSN_SSOCOOKIE_INTERVAL_SEC = 10

_STEALTH_INIT = STEALTH_INIT_SCRIPT


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


NINTENDO_ACCOUNT_URL = "https://ec.nintendo.com/my/transactions/"
# Nintendo session cookies that prove we can read the eShop purchase history.
# Capturing any nintendo.com cookie isn't enough — sign-in completes on
# accounts.nintendo.com, but the eShop session cookies only get set once we're
# actually on ec.nintendo.com, so we must land there before reading the jar.
_NINTENDO_SESSION_COOKIES = (
    "MIST",
    "JViDD",
    "_gh_sess",
    "NASID",
    "ecsid",
    "__Secure-next-auth.session-token",
)


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
        from nintendo_client import PLAYWRIGHT_REQUEST_TIMEOUT_MS, probe_session_id_token

        return bool(
            probe_session_id_token(
                context.request.get, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS
            ).get("ok")
        )
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


def _epic_error_from_text(text: str) -> dict[str, str] | None:
    """Detect Epic's corrective-action gate in a redirect body (HTML-wrapped JSON safe)."""
    from epic_client import corrective_action_in_text

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
            html = ""
            if not code:
                try:
                    html = main.content()
                except Exception:
                    html = ""
                code = _epic_code_from_text(html)
            if code:
                from epic_client import (
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
    return ""


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
        from psn_client import PsnAuthError, validate_npsso
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
    from auth.epic_wishlist_session import (
        graphql_debug_entry,
        is_epic_graphql_url,
        storefront_bounced_to_home,
        wishlist_capture_complete_from_html,
        wishlist_graphql_ok,
    )

    wishlist_loaded = False
    saw_id_login = False
    did_post_login_nav = False
    # Reader-thread handlers must NOT call response.json()/getResponseBody — that
    # issues another CDP command and waits on the very thread that pumps the
    # reply, deadlocking until timeout and freezing cookie polling. Just stash
    # candidate responses; the polling thread parses their bodies safely.
    candidates: list[Any] = []
    seen_graphql: list[dict[str, Any]] = []

    try:
        _debug_path = profile_dir("epic_wishlist").parent / "epic_wishlist_connect_debug.json"
    except Exception:  # noqa: BLE001
        _debug_path = None

    def _write_debug() -> None:
        if _debug_path is None:
            return
        try:
            _debug_path.parent.mkdir(parents=True, exist_ok=True)
            _debug_path.write_text(
                json.dumps(seen_graphql[:50], indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def on_response(response) -> None:
        try:
            if not is_epic_graphql_url(response.url or ""):
                return
            if response.status == 200:
                candidates.append(response)
        except Exception:  # noqa: BLE001
            pass

    def _drain_candidates() -> bool:
        found = False
        while candidates:
            resp = candidates.pop(0)
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                continue
            try:
                seen_graphql.append(graphql_debug_entry(resp.url or "", payload))
            except Exception:  # noqa: BLE001
                pass
            if wishlist_graphql_ok(payload):
                found = True
        if seen_graphql:
            _write_debug()
        return found

    page.on("response", on_response)
    try:
        page.goto(epic_store_login_url(), wait_until="domcontentloaded", timeout=25_000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        if not wishlist_loaded and _drain_candidates():
            wishlist_loaded = True
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
            if not wishlist_loaded and _drain_candidates():
                wishlist_loaded = True
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


def _xbox_signed_in_state(context, page=None) -> dict | None:
    """Return parsed wishlist SSR when signed in (else ``None``).

    Prefer the live page document after ``page.goto`` — cookie-only HTTP GET
    often returns a signed-out ``__PRELOADED_STATE__`` on xbox.com.
    """
    if page is not None:
        try:
            url = (page.url or "").lower()
            if "xbox.com" in url:
                state = _parse_xbox_preloaded_state(page.content())
                if state:
                    user = state.get("user") or {}
                    if not user.get("isSignedIn"):
                        return None
                    page_meta = (state.get("pageRequestMetadata") or {}).get("/wishlist") or {}
                    err = page_meta.get("error") or {}
                    if err.get("httpStatusCode") == 403:
                        return None
                    return state
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


def _xbox_capture_wishlist_api(page, sniffer, *, timeout_s: float = 12.0) -> None:
    """After sign-in, linger on the wishlist so the Emerald XHR fires and is sniffed."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if sniffer.token:
            return
        page.wait_for_timeout(500)


def _extract_xbox_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open xbox.com/wishlist, wait for MSA sign-in (detected via SSR HTML),
    then capture the Emerald wishlist API token for headless replay. The
    persistent profile remains the fallback credential.
    """
    from auth.xbox_wishlist_capture import WishlistApiSniffer

    sniffer = WishlistApiSniffer()
    try:
        page.on("response", sniffer.on_response)
    except Exception:  # noqa: BLE001
        pass

    try:
        page.goto(XBOX_WISHLIST_URL, wait_until="domcontentloaded", timeout=20000)
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_msg = 0.0
    while time.time() < deadline:
        url = (page.url or "").lower()
        on_login = (
            "login.live.com" in url
            or "login.microsoftonline" in url
            or "signin" in url
            or "account.microsoft" in url
        )
        # xbox.com bakes __PRELOADED_STATE__ into the HTML at load time and
        # never refreshes it client-side, and a cookie-only HTTP GET returns a
        # signed-out payload. So once the user is back on xbox.com we must
        # re-navigate to pull a fresh SSR that reflects the new MSA cookies.
        # Never navigate while they're mid-login on a Microsoft page.
        if not on_login and "xbox.com" in url:
            try:
                page.goto(XBOX_WISHLIST_URL, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                pass

        state = _xbox_signed_in_state(context, page)
        if state is not None:
            if session:
                session.emit(
                    "waiting_for_user",
                    {"message": "Signed in \u2014 capturing your wishlist session..."},
                )
            _xbox_capture_wishlist_api(page, sniffer)
            sniffer.dump()
            creds = {"XBOX_WISHLIST_PROFILE": "ready"}
            creds.update(sniffer.creds())
            return creds

        now = time.time()
        if session and now - last_msg > 8:
            last_msg = now
            if on_login:
                msg = "Sign in to your Microsoft account in the browser window."
            elif "xbox.com" not in url:
                msg = "Open xbox.com/wishlist after signing in."
            else:
                msg = "Signed in \u2014 waiting for xbox.com to issue your wishlist session."
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))

    raise RuntimeError(
        "Could not detect an Xbox sign-in \u2014 sign in to xbox.com/wishlist "
        "and keep the window open until it closes."
    )


NINTENDO_WISHLIST_URL = "https://www.nintendo.com/us/wish-list/"
NINTENDO_WISHLIST_POLL_SEC = 2.5


def _nintendo_wishlist_session_ready(html: str, url: str, api_payloads: list[Any]) -> bool:
    """True when storefront GraphQL confirms a signed-in wish-list session."""
    from fetch_nintendo_wishlist import _wishlist_graphql_ok, parse_wishlist_sources

    u = (url or "").lower()
    if "accounts.nintendo.com/login" in u:
        return False
    if any(_wishlist_graphql_ok(p) for p in api_payloads):
        return True
    return bool(parse_wishlist_sources(html, api_payloads))


def _extract_nintendo_wishlist_inline(page, context, session) -> dict[str, str]:
    """Open nintendo.com/us/wish-list/, wait for sign-in, return marker cred."""
    from fetch_nintendo_wishlist import (
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
        urls = [(pg.url or "").lower() for pg in live]
        if len(live) > 1:
            main_url = (main.url or "").lower()
            # Don't steal focus from the Ubisoft SDK while it hands off to the opener.
            if "connect.ubisoft.com/login" in main_url or UBISOFT_SUCCESS_URL in main_url:
                try:
                    main.bring_to_front()
                except Exception:
                    pass
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

    with launch_persistent_profile(user_data, headless=False) as context:
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
        page = context.pages[0] if context.pages else context.new_page()

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
