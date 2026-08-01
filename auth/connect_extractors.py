"""Reusable credential extractors for headed browser connect flows."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from typing import Any

HUMBLE_LIBRARY_URL = "https://www.humblebundle.com/home/library"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
BATTLENET_GAMES_URL = "https://account.battle.net/games"
BATTLENET_ACCOUNT_API = "https://account.battle.net/api/games-and-subs"
# Per-message-key dedupe interval kept for tests that monkeypatch these.
_BATTLENET_LOG_INTERVAL_SEC = 4.0
_battlenet_last_log_by_key: dict[str, float] = {}
_battlenet_log_path: Any | None = None


def pick_gog_al_from_cookies(cookies: list[dict]) -> str:
    gog_al = next((c["value"] for c in cookies if c.get("name") == "gog-al" and c.get("value")), "")
    if gog_al:
        return str(gog_al)
    parts = []
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if "gog.com" not in domain:
            continue
        name = c.get("name") or ""
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    header = "; ".join(parts)
    if "gog-al=" in header:
        return header.split("gog-al=")[-1].split(";")[0].strip()
    return ""


def _cookie_header(cookies: list[dict], domains: tuple[str, ...]) -> str:
    parts: list[str] = []
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if not any(domain.endswith(d.lstrip(".")) or d.lstrip(".") in domain for d in domains):
            continue
        name = c.get("name") or ""
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _humble_has_session(context: Any) -> bool:
    try:
        resp = context.request.get(HUMBLE_ORDERS_API, timeout=15_000)
        if resp.status == 200:
            body = resp.text().strip()
            if body.startswith("[") or body.startswith("{"):
                return True
        if resp.status in (401, 403):
            return False
    except Exception:  # noqa: BLE001
        pass
    return False


def _battlenet_has_session(context: Any) -> bool:
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if domain.endswith("battle.net") and c.get("name") and c.get("value"):
            return True
    return False


class HeaderSniffer:
    """Capture request headers (e.g. Authorization Bearer, Ubisoft API headers)."""

    def __init__(
        self,
        *,
        url_substr: str,
        fields: dict[str, str],
        normalize: Callable[[str | None], str | None] | None = None,
    ) -> None:
        self.url_substr = url_substr.lower()
        self.fields = {k.lower(): v for k, v in fields.items()}
        self.normalize = normalize
        self.captured: dict[str, str] = {}

    def attach(self, context: Any) -> None:
        def on_request(request: Any) -> None:
            url = (getattr(request, "url", None) or "").lower()
            if self.url_substr not in url:
                return
            headers = getattr(request, "headers", {}) or {}
            for header_key, cred_key in self.fields.items():
                val = headers.get(header_key) or headers.get(header_key.title())
                if not val:
                    continue
                if self.normalize and cred_key.endswith("TOKEN"):
                    norm = self.normalize(val)
                    if norm:
                        self.captured[cred_key] = norm
                else:
                    self.captured[cred_key] = str(val).strip()

        context.on("request", on_request)

    def ready(self) -> bool:
        return all(self.captured.get(k) for k in self.fields.values())

    def creds(self) -> dict[str, str]:
        return dict(self.captured)


class GraphqlResponseSniffer:
    """Queue GraphQL response bodies without parsing on the CDP callback thread."""

    def __init__(
        self,
        *,
        url_match: Callable[[str], bool],
        accept: Callable[[dict[str, Any]], bool],
    ) -> None:
        self.url_match = url_match
        self.accept = accept
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self.matched = False

    def attach(self, page: Any) -> None:
        def on_response(response: Any) -> None:
            try:
                url = getattr(response, "url", None) or ""
                if not self.url_match(url):
                    return
                if int(getattr(response, "status", 0) or 0) != 200:
                    return
                payload = response.json()
                if not isinstance(payload, dict):
                    return
                self._queue.put(payload)
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

    def drain(self) -> bool:
        changed = False
        while True:
            try:
                payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if self.accept(payload):
                with self._lock:
                    self.matched = True
                changed = True
        return changed

    @property
    def success(self) -> bool:
        with self._lock:
            return self.matched


def extract_gog_session(context: Any) -> dict[str, str] | None:
    gog_al = pick_gog_al_from_cookies(context.cookies())
    if gog_al:
        return {"GOG_AL": gog_al}
    return None


def gog_connect_hint(page: Any) -> str:
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "auth" in url:
        return "Sign in to your GOG account in the browser window."
    return (
        "Sign in at gog.com if prompted. We'll save your session automatically "
        "once you're logged in."
    )


def extract_humble_session(context: Any, page: Any) -> dict[str, str] | None:
    if _humble_has_session(context):
        try:
            page.goto(HUMBLE_LIBRARY_URL, wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass
        return {"HUMBLE_PROFILE": "ready"}
    return None


def humble_connect_hint(page: Any) -> str:
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "sign" in url and "library" not in url:
        return "Sign in to Humble Bundle in the browser window (email or Google)."
    if "humblebundle.com" not in url:
        return "Open humblebundle.com and sign in if prompted."
    return "On humblebundle.com? We'll open your library to confirm the session."


def _battlenet_xsrf_from_cookies(cookies: list[dict]) -> str:
    for c in cookies:
        if (c.get("name") or "") == "XSRF-TOKEN" and c.get("value"):
            return str(c["value"]).strip()
    return ""


def _battlenet_log(message: str, *, key: str | None = None) -> None:
    """Rate-limited stderr + on-disk tee for frozen Tray builds."""
    from auth.connect_log import connect_log

    connect_log("battlenet", message, key=key)


def _battlenet_resolve_cookie_header(
    context: Any,
    page: Any | None,
    sniffer: BattleNetGamesAndSubsSniffer | None,
) -> str:
    """Build a Cookie header from CDP dump, url-scoped dump, then sniffer."""
    try:
        cookies = context.cookies()
    except Exception:  # noqa: BLE001
        cookies = []
    header = _cookie_header(cookies, (".battle.net", "battle.net"))
    if header:
        return header
    scoped = _battlenet_cookies_via_urls(context, page)
    header = _cookie_header(scoped, (".battle.net", "battle.net"))
    if header:
        return header
    if sniffer is not None:
        _verified, sniffed, _status = sniffer.snapshot()
        if sniffed:
            return sniffed
    return ""


def _battlenet_cookie_count(cookies: list[dict]) -> tuple[int, bool]:
    count = 0
    has_xsrf = False
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if not domain.endswith("battle.net"):
            continue
        if c.get("name") and c.get("value") is not None:
            count += 1
            if c.get("name") == "XSRF-TOKEN":
                has_xsrf = True
    return count, has_xsrf


class BattleNetGamesAndSubsSniffer:
    """Treat a live games-and-subs 200 as session proof (any tab)."""

    URL_SUBSTR = "account.battle.net/api/games-and-subs"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.verified = False
        self.cookie_header = ""
        self.status = 0
        self.last_url = ""

    def attach(self, context: Any) -> None:
        def on_request(request: Any) -> None:
            url = (getattr(request, "url", None) or "").lower()
            if self.URL_SUBSTR not in url:
                return
            headers = getattr(request, "headers", {}) or {}
            cookie = headers.get("cookie") or headers.get("Cookie") or ""
            if cookie:
                with self._lock:
                    self.cookie_header = str(cookie).strip()
                    self.last_url = getattr(request, "url", None) or url

        def on_response(response: Any) -> None:
            url = (getattr(response, "url", None) or "").lower()
            if self.URL_SUBSTR not in url:
                return
            status = int(getattr(response, "status", 0) or 0)
            if status != 200:
                return
            cookie = ""
            req = getattr(response, "request", None)
            if req is not None:
                headers = getattr(req, "headers", {}) or {}
                cookie = headers.get("cookie") or headers.get("Cookie") or ""
            with self._lock:
                self.verified = True
                self.status = status
                self.last_url = getattr(response, "url", None) or url
                if cookie:
                    self.cookie_header = str(cookie).strip()

        context.on("request", on_request)
        context.on("response", on_response)

    def snapshot(self) -> tuple[bool, str, int]:
        with self._lock:
            return self.verified, self.cookie_header, self.status

    def matched_url(self) -> str:
        with self._lock:
            return self.last_url

    def creds_from(self, context: Any) -> dict[str, str] | None:
        verified, sniffed, _status = self.snapshot()
        if not verified:
            return None
        cookies = context.cookies()
        header = _cookie_header(cookies, (".battle.net", "battle.net"))
        if not header:
            header = sniffed
        if not header:
            return None
        return {"BATTLENET_COOKIE": header}


def build_battlenet_games_sniffer() -> BattleNetGamesAndSubsSniffer:
    return BattleNetGamesAndSubsSniffer()


def _battlenet_cookies_via_urls(context: Any, page: Any | None) -> list[dict]:
    """Prefer Network.getCookies with explicit urls on the live page session."""
    getter = getattr(context, "cookies_for_urls", None)
    if not callable(getter):
        return []
    urls = [
        "https://account.battle.net/",
        "https://account.battle.net/games",
        BATTLENET_ACCOUNT_API,
        "https://battle.net/",
    ]
    page_url = (getattr(page, "url", None) or "") if page is not None else ""
    if page_url.startswith("http"):
        urls.insert(0, page_url)
    try:
        cookies = getter(urls, page=page)
    except Exception:  # noqa: BLE001
        return []
    return cookies if isinstance(cookies, list) else []


def _battlenet_probe_status(page: Any, *, xsrf: str = "") -> dict[str, Any]:
    """In-page games-and-subs probe; returns {ok, status, href, origin}."""
    if page is None:
        return {"ok": False, "status": 0, "href": "", "origin": ""}
    xsrf_js = json.dumps(xsrf or "")
    try:
        result = page.evaluate(
            f"""async () => {{
                try {{
                    const headers = {{
                        Accept: 'application/json, text/plain, */*',
                    }};
                    let xsrf = {xsrf_js};
                    if (!xsrf) {{
                        const m = document.cookie.match(/(?:^|;\\s*)XSRF-TOKEN=([^;]+)/);
                        if (m) {{
                            try {{ xsrf = decodeURIComponent(m[1].trim()); }}
                            catch (e) {{ xsrf = m[1].trim(); }}
                        }}
                    }} else {{
                        try {{ xsrf = decodeURIComponent(xsrf); }}
                        catch (e) {{}}
                    }}
                    if (xsrf) headers['X-XSRF-TOKEN'] = xsrf;
                    const res = await fetch({json.dumps(BATTLENET_ACCOUNT_API)}, {{
                        credentials: 'include',
                        headers,
                    }});
                    return {{
                        ok: res.status === 200,
                        status: res.status,
                        href: String(location.href || ''),
                        origin: String(location.origin || ''),
                    }};
                }} catch (e) {{
                    return {{
                        ok: false,
                        status: 0,
                        href: String(location.href || ''),
                        origin: String(location.origin || ''),
                    }};
                }}
            }}""",
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        return {"ok": False, "status": 0, "href": "", "origin": ""}
    if isinstance(result, dict):
        return {
            "ok": bool(result.get("ok")),
            "status": int(result.get("status") or 0),
            "href": str(result.get("href") or ""),
            "origin": str(result.get("origin") or ""),
        }
    return {"ok": False, "status": 0, "href": "", "origin": ""}


def _battlenet_probe_via_page(page: Any, *, xsrf: str = "") -> bool:
    """Verify games-and-subs via in-page fetch (real jar + origin), like PSN/XBL."""
    return bool(_battlenet_probe_status(page, xsrf=xsrf).get("ok"))


def extract_battlenet_session(
    context: Any,
    page: Any | None = None,
    *,
    sniffer: BattleNetGamesAndSubsSniffer | None = None,
) -> dict[str, str] | None:
    """Complete Connect from games-and-subs proof; external probe is last resort.

    Do **not** import ``battlenet_client`` (and ``browser_cookie3``) before the
    Games SPA success paths — a failed frozen import used to return None forever
    and skip all logging.

    If the in-page probe returns 401, never complete from sniffer/external stale
    cookies — keep polling so the user can sign in.
    """
    try:
        cookies = context.cookies()
    except Exception:  # noqa: BLE001
        cookies = []
    header = _cookie_header(cookies, (".battle.net", "battle.net"))
    xsrf = _battlenet_xsrf_from_cookies(cookies)
    cookie_count, has_xsrf = _battlenet_cookie_count(cookies)
    page_url = (getattr(page, "url", None) or "") if page is not None else ""
    sniffer_verified = False
    sniffer_status = 0
    sniffed_header = ""
    sniffer_url = ""
    if sniffer is not None:
        sniffer_verified, sniffed_header, sniffer_status = sniffer.snapshot()
        sniffer_url = sniffer.matched_url()

    # In-page probe first when we have a page: authoritative for "need login".
    probe: dict[str, Any] | None = None
    if page is not None:
        probe = _battlenet_probe_status(page, xsrf=xsrf)
        _battlenet_log(
            f"poll ok={probe.get('ok')} status={probe.get('status')} "
            f"url={page_url!r} href={probe.get('href')!r} origin={probe.get('origin')!r} "
            f"cookies={cookie_count} xsrf={has_xsrf} "
            f"sniffer_ok={sniffer_verified} sniffer_status={sniffer_status} "
            f"sniffer_url={sniffer_url!r} header_empty={not bool(header)}",
            key="poll",
        )
        if int(probe.get("status") or 0) == 401:
            if sniffer_verified:
                _battlenet_log(
                    f"in-page 401 — ignoring sniffer (url={sniffer_url!r})",
                    key="ignore-sniffer-401",
                )
            return None
        if probe.get("ok"):
            header = _battlenet_resolve_cookie_header(context, page, sniffer)
            if header:
                _battlenet_log("in-page 200 — session ready", key="inpage-ready")
                return {"BATTLENET_COOKIE": header}
            _battlenet_log("in-page 200 but cookie dump empty — waiting", key="empty-cookies")
            return None

    # Sniffer: games-and-subs 200 only (narrow URL). Skip if page said 401 above.
    if sniffer is not None:
        sniffed_creds = sniffer.creds_from(context)
        if sniffed_creds:
            _battlenet_log(
                f"games-and-subs sniffer 200 — session ready url={sniffer.matched_url()!r}",
                key="sniffer-ready",
            )
            return sniffed_creds
        if sniffer_verified:
            header = _battlenet_resolve_cookie_header(context, page, sniffer)
            if header:
                _battlenet_log(
                    f"sniffer verified + cookies — session ready url={sniffer_url!r}",
                    key="sniffer-retry",
                )
                return {"BATTLENET_COOKIE": header}

    if not _battlenet_has_session(context):
        return None
    if not header:
        header = sniffed_header or _battlenet_resolve_cookie_header(context, page, sniffer)
    if not header:
        return None

    # External probe only — needs battlenet_client (requests). Never gate above on this.
    try:
        from clients.battlenet_client import BattleNetAuthError, probe_session
    except Exception as exc:  # noqa: BLE001
        _battlenet_log(f"external probe import failed: {exc}", key="import-fail")
        return None
    try:
        probe_session(header)
    except BattleNetAuthError as exc:
        _battlenet_log(f"external probe rejected: {exc}", key="external-reject")
        return None
    _battlenet_log("external probe accepted", key="external-ok")
    return {"BATTLENET_COOKIE": header}


def battlenet_connect_hint(page: Any) -> str:
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "authorize" in url:
        return "Sign in to your Battle.net account in the browser window."
    if "battle.net" not in url:
        return "Open account.battle.net/games after signing in."
    return (
        "On your Games page? Wait until your library list finishes loading, "
        "then we'll save the session automatically."
    )


def extract_ea_bearer_session(
    context: Any,
    *,
    sniffer: HeaderSniffer,
) -> dict[str, str] | None:
    from clients.ea_session import probe_ea_token

    if not sniffer.captured.get("EA_BEARER_TOKEN"):
        return None
    token = sniffer.captured["EA_BEARER_TOKEN"]
    cookies = context.cookies()
    probe = probe_ea_token(token, cookies)
    if probe.get("ok"):
        return {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": token}
    err = (probe.get("error") or "")[:200]
    if "PersistedQueryNotFound" in err:
        return {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": token}
    sniffer.captured.clear()
    return None


def ea_connect_hint(page: Any, *, saw_token: bool) -> str:
    url = (getattr(page, "url", None) or "").lower()
    if "signin.ea.com" in url or "/login" in url:
        return "Sign in to your EA account in the browser window."
    if saw_token:
        return "Verifying your EA session — keep the window open."
    return "Signed in — wait for the deals page to finish loading so we can save your session."


def build_ea_header_sniffer() -> HeaderSniffer:
    from clients.ea_session import EA_GRAPHQL_HOST, normalize_bearer

    return HeaderSniffer(
        url_substr=EA_GRAPHQL_HOST,
        fields={"authorization": "EA_BEARER_TOKEN"},
        normalize=normalize_bearer,
    )


class DeferredGraphqlResponseSniffer:
    """Queue raw GraphQL responses; parse on drain() to avoid CDP callback deadlocks."""

    def __init__(
        self,
        *,
        url_match: Callable[[str], bool],
        accept: Callable[[dict[str, Any]], bool],
        debug_entry: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.url_match = url_match
        self.accept = accept
        self.debug_entry = debug_entry
        self._pending: list[Any] = []
        self._lock = threading.Lock()
        self.matched = False
        self.debug_log: list[dict[str, Any]] = []

    def attach(self, page: Any) -> None:
        def on_response(response: Any) -> None:
            try:
                url = getattr(response, "url", None) or ""
                if not self.url_match(url):
                    return
                if int(getattr(response, "status", 0) or 0) != 200:
                    return
                self._pending.append(response)
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

    def drain(self) -> bool:
        changed = False
        while self._pending:
            resp = self._pending.pop(0)
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            if self.debug_entry is not None:
                try:
                    self.debug_log.append(self.debug_entry(getattr(resp, "url", "") or "", payload))
                except Exception:  # noqa: BLE001
                    pass
            if self.accept(payload):
                with self._lock:
                    self.matched = True
                changed = True
        return changed

    @property
    def success(self) -> bool:
        with self._lock:
            return self.matched


def build_epic_wishlist_graphql_sniffer() -> DeferredGraphqlResponseSniffer:
    from auth.epic_wishlist_session import graphql_debug_entry, is_epic_graphql_url, wishlist_graphql_ok

    return DeferredGraphqlResponseSniffer(
        url_match=is_epic_graphql_url,
        accept=wishlist_graphql_ok,
        debug_entry=graphql_debug_entry,
    )


class EpicEmailExistsCfSniffer:
    """Stash ``/id/api/email/exists`` responses; drain CF challenge URLs off-thread.

    Cloudflare often returns non-200 HTML for the email-exists XHR. Epic dumps that
    body into the login form error so the challenge script never runs — Connect
    must open the ``__cf_chl_tk`` URL as a top-level document instead.
    """

    def __init__(self) -> None:
        self._pending: list[Any] = []
        self._seen_tokens: set[str] = set()
        self._lock = threading.Lock()

    def attach(self, page: Any) -> None:
        def on_response(response: Any) -> None:
            try:
                url = (getattr(response, "url", None) or "").lower()
                if "/id/api/email/exists" not in url:
                    return
                self._pending.append(response)
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

    def drain_challenge_url(self) -> str | None:
        from urllib.parse import parse_qs, urlparse

        from auth.epic_wishlist_session import extract_epic_cf_challenge_url

        while self._pending:
            resp = self._pending.pop(0)
            try:
                body = resp.text()
            except Exception:  # noqa: BLE001
                continue
            url = extract_epic_cf_challenge_url(body or "")
            if not url:
                continue
            qs = parse_qs(urlparse(url).query)
            token = (qs.get("__cf_chl_tk") or [None])[0] or url
            with self._lock:
                if token in self._seen_tokens:
                    continue
                self._seen_tokens.add(token)
            return url
        return None


UBISOFT_API_HOST = "public-ubiservices.ubi.com"


def build_ubisoft_header_sniffer() -> HeaderSniffer:
    return HeaderSniffer(
        url_substr=UBISOFT_API_HOST,
        fields={
            "authorization": "UBISOFT_AUTH",
            "ubi-sessionid": "UBISOFT_SESSION_ID",
            "ubi-appid": "UBISOFT_APP_ID",
        },
    )


def extract_ubisoft_session(sniffer: HeaderSniffer) -> dict[str, str] | None:
    if sniffer.captured.get("UBISOFT_AUTH") and sniffer.captured.get("UBISOFT_SESSION_ID"):
        return sniffer.creds()
    return None


def ubisoft_session_captured(sniffer: HeaderSniffer) -> bool:
    return bool(
        sniffer.captured.get("UBISOFT_AUTH") and sniffer.captured.get("UBISOFT_SESSION_ID")
    )


def ubisoft_connect_hint(
    *,
    urls: list[str],
    seen_success: bool,
    captured: bool,
) -> str:
    joined = " ".join(urls)
    if "account.ubisoft" in joined or "login" in joined:
        return (
            "Finish Ubisoft sign-in and 2FA in the browser window (use the popup if it "
            "stays open). Close DevTools if you see a yellow 'Debugger paused' banner."
        )
    if seen_success and not captured:
        return "Signed in — opening your Ubisoft games list to finish capturing the session."
    if not captured:
        return "Signed in? Open your Ubisoft Connect games list so we can capture the session."
    return "Almost there — keep the window open while we finish capturing your session."


NINTENDO_ACCOUNT_URL = "https://ec.nintendo.com/my/transactions/"
_NINTENDO_SESSION_COOKIES = (
    "MIST",
    "JViDD",
    "_gh_sess",
    "NASID",
    "ecsid",
    "__Secure-next-auth.session-token",
)


def nintendo_has_session(context: Any) -> bool:
    """True when known eShop session cookies exist on ec.nintendo.com."""
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if not domain.startswith("ec.nintendo.com"):
            continue
        name = c.get("name") or ""
        if name in _NINTENDO_SESSION_COOKIES and c.get("value"):
            return True
    return False


def nintendo_session_has_id_token(context: Any) -> bool:
    """Verify /api/auth/session returns an idToken (GraphQL prerequisite)."""
    try:
        from clients.nintendo_client import PLAYWRIGHT_REQUEST_TIMEOUT_MS, probe_session_id_token

        return bool(
            probe_session_id_token(
                context.request.get, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS
            ).get("ok")
        )
    except Exception:  # noqa: BLE001
        return False


def extract_nintendo_session(context: Any) -> dict[str, str] | None:
    if not nintendo_has_session(context) or not nintendo_session_has_id_token(context):
        return None
    header = _cookie_header(context.cookies(), ("nintendo.com",))
    if header:
        return {"NINTENDO_COOKIE": header}
    return None


def nintendo_connect_hint(page: Any, *, on_account: bool) -> str:
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "authorize" in url:
        return "Sign in to your Nintendo Account in the browser window."
    if on_account:
        return "Signed in — opening your eShop transactions page to capture the session."
    return "Loading your Nintendo eShop transactions — keep the window open."


def cookie_header(cookies: list[dict], domains: tuple[str, ...]) -> str:
    return _cookie_header(cookies, domains)
