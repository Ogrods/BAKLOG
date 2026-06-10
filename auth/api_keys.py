"""Browser-based API key extraction for form providers (Steam, itch, ITAD, Xbox)."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from auth.cdp_compat import click_by_text

if TYPE_CHECKING:
    from auth.runner import AuthSession

POLL_SEC = 0.5
SUCCESS_WAIT_SEC = 300

# Tri-state result for API-key checks so callers can tell a genuinely rejected
# key apart from a transient network failure (no connection, timeout, 5xx).
# Marking a provider "expired" on a network blip wrongly nags the user to
# re-sign-in; an "unreachable" result lets the UI say "try again" instead.
KEY_VALID = "valid"
KEY_INVALID = "invalid"
KEY_UNREACHABLE = "unreachable"

STEAM_LOGIN_URL = "https://steamcommunity.com/login/home/?goto=dev%2Fapikey"
STEAM_APIKEY_URL = "https://steamcommunity.com/dev/apikey"
ITCH_KEYS_URL = "https://itch.io/user/settings/api-keys"
ITCH_LOGIN_URL = "https://itch.io/login"
ITAD_APPS_URL = "https://isthereanydeal.com/apps/my/"
XBL_DASHBOARD_URL = "https://xbl.io/dashboard"

_STEAM_KEY_RE = re.compile(r"\b([0-9A-F]{32})\b", re.I)
_STEAM_ID_RE = re.compile(r"\b(7656119\d{10})\b")
_ITCH_KEY_RE = re.compile(r"\b([a-zA-Z0-9]{20,64})\b")
_ITAD_KEY_RE = re.compile(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.I)
_XBL_KEY_RE = re.compile(r"\b([a-zA-Z0-9]{24,128})\b")


def _wait_loop(
    page,
    *,
    session: AuthSession | None,
    message: str,
    try_extract,
) -> dict[str, str]:
    deadline = time.time() + SUCCESS_WAIT_SEC
    while time.time() < deadline:
        try:
            creds = try_extract()
            if creds:
                return creds
        except Exception:
            pass
        if session:
            session.emit("waiting_for_user", {"message": message})
        page.wait_for_timeout(int(POLL_SEC * 1000))
    raise RuntimeError(message)


def _steam_steam_id(page) -> str:
    try:
        sid = page.evaluate(
            """() => {
                if (typeof g_steamID !== 'undefined' && g_steamID) return String(g_steamID);
                const el = document.querySelector('[data-steamid]');
                if (el) return el.getAttribute('data-steamid') || '';
                const m = document.documentElement.innerHTML.match(/g_steamID\\s*=\\s*"(\\d+)"/);
                return m ? m[1] : '';
            }"""
        )
        if isinstance(sid, str) and _STEAM_ID_RE.fullmatch(sid.strip()):
            return sid.strip()
    except Exception:
        pass
    try:
        page.goto("https://steamcommunity.com/my/profile", wait_until="domcontentloaded", timeout=15000)
        body = page.content()
        m = _STEAM_ID_RE.search(body)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _steam_try_register_key(page) -> None:
    """Register a Web API key if the dev page shows the domain form."""
    try:
        domain = page.locator('input[name="domain"], #domain, input[placeholder*="domain" i]').first
        if domain.count() == 0:
            return
        domain.fill("127.0.0.1", timeout=3000)
        for label in ("Register", "Request", "Create"):
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(2500)
                return
        submit = page.locator('button[type="submit"], input[type="submit"]').first
        if submit.count() > 0:
            submit.click(timeout=3000)
            page.wait_for_timeout(2500)
    except Exception:
        pass


def _steam_extract_from_page(page) -> dict[str, str] | None:
    url = (page.url or "").lower()
    if "login" in url and "steamcommunity.com" in url:
        return None
    if "steamcommunity.com" not in url or "apikey" not in url:
        try:
            page.goto(STEAM_APIKEY_URL, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            return None
    _steam_try_register_key(page)
    body = page.content()
    m = re.search(r"Key[:\s#]*([0-9A-F]{32})", body, re.I)
    api_key = m.group(1) if m else ""
    if not api_key:
        keys = _STEAM_KEY_RE.findall(body)
        api_key = keys[0] if keys else ""
    steam_id = _steam_steam_id(page)
    if not api_key or not steam_id:
        return None
    return {"STEAM_API_KEY": api_key, "STEAM_ID": steam_id}


def _validate_steam(creds: dict[str, str]) -> None:
    import requests

    key = creds["STEAM_API_KEY"]
    sid = creds["STEAM_ID"]
    resp = requests.get(
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
        params={"key": key, "steamids": sid},
        timeout=20,
    )
    resp.raise_for_status()
    players = resp.json().get("response", {}).get("players") or []
    if not players:
        raise RuntimeError("Steam API key or SteamID64 is invalid — check sign-in and try again")


def extract_steam(page, context, session: AuthSession | None = None) -> dict[str, str]:
    def attempt() -> dict[str, str] | None:
        return _steam_extract_from_page(page)

    creds = _wait_loop(
        page,
        session=session,
        message="Sign in to Steam, then wait — we'll register your API key automatically.",
        try_extract=attempt,
    )
    _validate_steam(creds)
    return creds


def _scrape_keys_dom(page, *, pattern_hint: str = r"(?:API\s*Key|apikey|access[_\s-]?token)") -> list[str]:
    """Generic 'reveal-and-scrape' for API keys on a settings page."""
    try:
        result = page.evaluate(
            f"""() => {{
                const HINT = /{pattern_hint}/i;
                const looks = s => typeof s === 'string'
                    && /^[A-Za-z0-9_-]{{20,256}}$/.test(s)
                    && !/^(localhost|undefined|null|true|false|en[-_]US|en|github)$/i.test(s);

                // Reveal hidden keys — never click nav/external links
                document.querySelectorAll('button, [role="button"]').forEach(el => {{
                    if (el.tagName === 'A') return;
                    if (el.hasAttribute('target')) return;
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (/^(show|reveal|toggle)$/i.test(t)) {{
                        try {{ el.click(); }} catch (e) {{}}
                    }}
                }});

                const found = [];
                for (const inp of document.querySelectorAll('input')) {{
                    const v = inp.value || inp.getAttribute('value') || '';
                    if (looks(v) && v.length >= 30) found.push(v);
                }}
                for (const el of document.querySelectorAll('code, pre, textarea, [data-clipboard-text]')) {{
                    const v = (el.getAttribute && el.getAttribute('data-clipboard-text'))
                        || el.innerText || el.textContent || '';
                    const toks = v.match(/[A-Za-z0-9_-]{{30,256}}/g) || [];
                    for (const t of toks) if (looks(t)) found.push(t);
                }}
                const body = document.body ? document.body.innerText : '';
                let m;
                const re = /([A-Za-z0-9_-]{{30,256}})/g;
                // Strong hint context (within 60 chars after API Key label)
                const idx = body.search(HINT);
                if (idx >= 0) {{
                    const slice = body.slice(idx, idx + 400);
                    while ((m = re.exec(slice))) {{
                        if (looks(m[1])) found.push(m[1]);
                    }}
                }}
                return found;
            }}"""
        )
        if isinstance(result, list):
            return [str(x) for x in result if x]
    except Exception:
        pass
    return []


def validate_itch_key(key: str) -> str:
    """Check an itch.io API key. Returns KEY_VALID / KEY_INVALID / KEY_UNREACHABLE.

    A connection error, timeout, or 5xx is reported as ``KEY_UNREACHABLE`` so
    callers never treat a network blip as a rejected key.
    """
    import requests

    token = (key or "").strip()
    if not token:
        return KEY_INVALID
    try:
        resp = requests.get(f"https://itch.io/api/1/{token}/me", timeout=15)
    except requests.RequestException:
        return KEY_UNREACHABLE
    except Exception:  # noqa: BLE001 — defensive: any transport hiccup is "unreachable"
        return KEY_UNREACHABLE
    if resp.status_code == 200:
        return KEY_VALID
    if resp.status_code >= 500:
        return KEY_UNREACHABLE
    return KEY_INVALID


def _validate_itch(creds: dict[str, str]) -> bool:
    return validate_itch_key(creds.get("ITCH_API_KEY", "")) == KEY_VALID


def extract_itch(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Open itch API keys page, generate if needed, and validate against the API."""
    deadline = time.time() + SUCCESS_WAIT_SEC
    navigated = False
    generated = False
    last_message = 0.0
    while time.time() < deadline:
        url = (page.url or "").lower()

        # If the user is on a transient verification/login flow, just wait.
        if any(p in url for p in ("/login", "/register", "captcha", "verify")):
            if session and time.time() - last_message > 6:
                last_message = time.time()
                session.emit(
                    "waiting_for_user",
                    {"message": "Sign in / verify on itch.io. We'll wait until you're done."},
                )
            page.wait_for_timeout(1000)
            continue

        # Once on itch.io but not the keys page, go there (once).
        if "itch.io" in url and "/user/settings/api-keys" not in url and not navigated:
            try:
                page.goto(ITCH_KEYS_URL, wait_until="domcontentloaded", timeout=20000)
                navigated = True
                page.wait_for_timeout(1000)
            except Exception:
                page.wait_for_timeout(1000)
                continue

        if "/user/settings/api-keys" in (page.url or "").lower():
            # Validate every "long alphanumeric" token on the page against the itch API.
            candidates = _scrape_keys_dom(page, pattern_hint=r"API\s*Key|api[_\s-]?key|key")
            for token in candidates:
                if "/" in token or token.endswith("="):
                    continue
                if _validate_itch({"ITCH_API_KEY": token}):
                    return {"ITCH_API_KEY": token}

            # Generate a key if no working one was found yet.
            if not generated:
                try:
                    if click_by_text(
                        page,
                        ("generate new api key", "generate"),
                        tags=("button", "a", "input[type='submit']"),
                    ):
                        generated = True
                        page.wait_for_timeout(1500)
                except Exception:
                    pass

        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit(
                "waiting_for_user",
                {"message": "Sign in to itch.io. Once the API Keys page loads we'll save your key."},
            )
        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture an itch.io API key — sign in fully, then try Connect again."
    )


def _itad_register_app(page) -> None:
    """If no app exists, register one named 'Steam Backlog'."""
    try:
        for label in ("Register", "New app", "Create"):
            if click_by_text(page, (label.lower(),)):
                page.wait_for_timeout(1000)
                break
        # Fill any required title/name field
        for sel in ('input[name="title"]', 'input[name="name"]', 'input[type="text"]'):
            inp = page.locator(sel).first
            if inp.count() > 0:
                inp.fill("Steam Backlog", timeout=2500)
                break
        for label in ("Register", "Create", "Save"):
            if click_by_text(page, (label.lower(),), tags=("button", "input[type='submit']")):
                page.wait_for_timeout(2500)
                break
    except Exception:
        pass


def validate_itad_key(key: str) -> str:
    """Check an ITAD API key. Returns KEY_VALID / KEY_INVALID / KEY_UNREACHABLE.

    A connection error, timeout, or 5xx is reported as ``KEY_UNREACHABLE`` so
    callers never treat a network blip as a rejected key.
    """
    import requests

    token = (key or "").strip()
    if not token:
        return KEY_INVALID
    try:
        resp = requests.get(
            "https://api.isthereanydeal.com/games/lookup/v1",
            params={"key": token, "title": "Portal"},
            timeout=15,
        )
    except requests.RequestException:
        return KEY_UNREACHABLE
    except Exception:  # noqa: BLE001 — defensive: any transport hiccup is "unreachable"
        return KEY_UNREACHABLE
    if resp.status_code == 200:
        return KEY_VALID
    if resp.status_code >= 500:
        return KEY_UNREACHABLE
    return KEY_INVALID


def _validate_itad(creds: dict[str, str]) -> bool:
    return validate_itad_key(creds.get("ITAD_API_KEY", "")) == KEY_VALID


def _scrape_itad_uuids(page) -> list[str]:
    """Find all UUIDs on page DOM and input values; click Show buttons first."""
    try:
        result = page.evaluate(
            r"""() => {
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    if (el.tagName === 'A') return;
                    if (el.hasAttribute('target')) return;
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (/^(show|reveal|toggle)$/i.test(t)) {
                        try { el.click(); } catch (e) {}
                    }
                });
                const out = new Set();
                const RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
                document.querySelectorAll('input').forEach(inp => {
                    const v = inp.value || inp.getAttribute('value') || '';
                    const m = v.match(RE);
                    if (m) m.forEach(x => out.add(x));
                });
                document.querySelectorAll('code, pre, textarea, [data-clipboard-text]').forEach(el => {
                    const v = (el.getAttribute && el.getAttribute('data-clipboard-text'))
                        || el.innerText || el.textContent || '';
                    const m = v.match(RE);
                    if (m) m.forEach(x => out.add(x));
                });
                const body = document.body ? document.body.innerText : '';
                const m = body.match(RE);
                if (m) m.forEach(x => out.add(x));
                return Array.from(out);
            }"""
        )
        if isinstance(result, list):
            return [str(x) for x in result]
    except Exception:
        pass
    return []


def extract_itad(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Open ITAD apps page, register one if needed, scrape and validate the key."""
    deadline = time.time() + SUCCESS_WAIT_SEC
    navigated = False
    registered = False
    expanded_apps = False
    last_message = 0.0

    while time.time() < deadline:
        url = (page.url or "").lower()

        if any(p in url for p in ("oauth/login", "auth/login", "captcha", "verify")):
            if session and time.time() - last_message > 6:
                last_message = time.time()
                session.emit(
                    "waiting_for_user",
                    {"message": "Sign in to IsThereAnyDeal. We'll wait until you're done."},
                )
            page.wait_for_timeout(1000)
            continue

        if "isthereanydeal.com" in url and "/apps/" not in url and not navigated:
            try:
                page.goto(ITAD_APPS_URL, wait_until="domcontentloaded", timeout=20000)
                navigated = True
                page.wait_for_timeout(1000)
            except Exception:
                page.wait_for_timeout(1000)
                continue

        if "isthereanydeal.com/apps" in (page.url or "").lower():
            # 1. Try any UUIDs already visible
            for uuid in _scrape_itad_uuids(page):
                if _validate_itad({"ITAD_API_KEY": uuid}):
                    return {"ITAD_API_KEY": uuid}

            # 2. Click into existing app rows (the key is on the app detail page)
            if not expanded_apps:
                try:
                    links = page.locator('a[href*="/apps/"]:not([href$="/apps/"]):not([href$="/apps/my/"])')
                    count = min(links.count(), 5)
                    for i in range(count):
                        try:
                            links.nth(i).click(timeout=3000)
                            page.wait_for_timeout(1500)
                            for uuid in _scrape_itad_uuids(page):
                                if _validate_itad({"ITAD_API_KEY": uuid}):
                                    return {"ITAD_API_KEY": uuid}
                            page.go_back(wait_until="domcontentloaded", timeout=10000)
                            page.wait_for_timeout(800)
                        except Exception:
                            try:
                                page.goto(ITAD_APPS_URL, wait_until="domcontentloaded", timeout=15000)
                            except Exception:
                                pass
                except Exception:
                    pass
                expanded_apps = True

            # 3. No app yet — register one
            if not registered:
                _itad_register_app(page)
                registered = True
                page.wait_for_timeout(2000)
                for uuid in _scrape_itad_uuids(page):
                    if _validate_itad({"ITAD_API_KEY": uuid}):
                        return {"ITAD_API_KEY": uuid}

        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit(
                "waiting_for_user",
                {
                    "message": (
                        "Sign in to IsThereAnyDeal. We'll open your app's key page automatically."
                    )
                },
            )
        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not capture an IsThereAnyDeal API key. Make sure you have at least one app "
        "registered at isthereanydeal.com/apps/my/, then click Connect again."
    )


def _xbl_signed_in(url: str) -> bool:
    u = (url or "").lower()
    if "xbl.io" not in u:
        return False
    if any(p in u for p in ("/login", "login.live.com", "account.microsoft.com")):
        return False
    return True


def _xbl_fetch_keys_json(page) -> list[str]:
    """Return OpenXBL key strings from the xbl.io keys endpoint via in-page XHR.

    xbl.io exposes the signed-in account's API keys as JSON at /keys (the same
    payload you'd see by visiting the URL). We fetch it from the page's own
    origin with ``credentials: 'include'`` so it carries the session cookie,
    instead of navigating the visible window there. That avoids flashing the
    raw JSON (and the 404 from probing /dashboard, /app) at the user before the
    connect window closes, and reads the key straight from the source of truth.
    """
    try:
        result = page.evaluate(
            """async () => {
                const urls = ['https://xbl.io/keys', 'https://xbl.io/app/keys'];
                const out = [];
                const seen = new Set();
                const push = v => {
                    if (typeof v !== 'string') return;
                    v = v.trim();
                    if (!v || seen.has(v)) return;
                    if (!/^[A-Za-z0-9_-]{24,128}$/.test(v)) return;
                    seen.add(v);
                    out.push(v);
                };
                for (const u of urls) {
                    try {
                        const res = await fetch(u, {
                            credentials: 'include',
                            headers: { Accept: 'application/json' },
                        });
                        if (!res.ok) continue;
                        const data = await res.json();
                        const keys = (data && data.keys) || [];
                        for (const k of keys) {
                            if (!k) continue;
                            push(k.key || k.apiKey || k.value || '');
                        }
                        if (out.length) return out;
                    } catch (e) {}
                }
                return out;
            }"""
        )
        if isinstance(result, list):
            return [str(x).strip() for x in result if isinstance(x, str) and x.strip()]
    except Exception:
        pass
    return []


def _xbl_scrape_key_candidates(page) -> list[str]:
    """Return ranked OpenXBL key candidates from the dashboard DOM/text.

    OpenXBL keys are alphanumeric and commonly 24-31 chars, so we accept a
    24-char floor (matching _XBL_KEY_RE) and return several ranked candidates
    rather than the first match. The caller validates each against the API, so
    relaxing the length never locks us onto a non-key token (CSRF/session ids).
    """
    try:
        result = page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const push = s => {
                    if (typeof s !== 'string') return;
                    s = s.trim();
                    if (!/^[A-Za-z0-9_-]{24,128}$/.test(s)) return;
                    if (/^(localhost|undefined|null|true|false)$/i.test(s)) return;
                    if (seen.has(s)) return;
                    seen.add(s);
                    out.push(s);
                };

                // Reveal hidden keys — only safe clicks (no nav, no targets)
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    const t = (el.innerText || '').trim().toLowerCase();
                    if (el.tagName === 'A') return;
                    if (el.hasAttribute('target')) return;
                    if (/^(show|reveal|toggle)$/i.test(t)) {
                        try { el.click(); } catch (e) {}
                    }
                });

                // 1. Highest confidence: token right after an "API key" label
                //    (xbl.io labels the key "authorizationCode" / "Authorization")
                const body = document.body ? document.body.innerText : '';
                const labelled = body.match(
                    /(?:authorizationCode|authorization|API\\s*Key|X-Authorization|apikey)[^A-Za-z0-9]+([A-Za-z0-9_-]{24,128})/ig
                ) || [];
                for (const chunk of labelled) {
                    const m = chunk.match(/([A-Za-z0-9_-]{24,128})\\s*$/);
                    if (m) push(m[1]);
                }
                // 2. data-clipboard-text (copy buttons usually carry the raw key)
                for (const el of document.querySelectorAll('[data-clipboard-text]')) {
                    push(el.getAttribute('data-clipboard-text') || '');
                }
                // 3. Input field values (readonly key fields)
                for (const inp of document.querySelectorAll('input')) {
                    push(inp.value || inp.getAttribute('value') || '');
                }
                // 4. Code/pre/textarea blocks
                for (const el of document.querySelectorAll('code, pre, textarea')) {
                    const v = el.innerText || el.textContent || '';
                    const toks = v.match(/[A-Za-z0-9_-]{24,128}/g) || [];
                    toks.forEach(push);
                }
                // 5. Bare body tokens (last resort)
                const bare = body.match(/[A-Za-z0-9_-]{24,128}/g) || [];
                bare.forEach(push);

                return out.slice(0, 8);
            }"""
        )
        if isinstance(result, list):
            return [s.strip() for s in result if isinstance(s, str) and s.strip()]
    except Exception:
        pass
    return []


def _xbox_key_check(key: str) -> str:
    """Probe an OpenXBL key: 'valid' | 'invalid' | 'rate_limited' (non-raising)."""
    from xbox_client import XboxAuthError, XboxClient, XboxRateLimitError

    try:
        XboxClient(key).get_account()
        return "valid"
    except XboxRateLimitError:
        return "rate_limited"
    except XboxAuthError:
        return "invalid"
    except Exception:  # noqa: BLE001
        return "invalid"


def _xbox_key_valid(key: str) -> bool:
    """Strict validity for scraped DOM candidates — used to filter candidates.

    A rate limit counts as invalid here on purpose: while throttled we can't
    tell a real key from a stray 24-128 char token, so we never lock onto one.
    """
    return _xbox_key_check(key) == "valid"


def extract_xbox(page, context, session: AuthSession | None = None) -> dict[str, str]:
    """Wait for OpenXBL sign-in, then scrape the API key from the dashboard."""
    captured: dict[str, str] = {}
    header_key: dict[str, str] = {}

    def on_request(request) -> None:
        if "xbl.io" not in (request.url or "").lower():
            return
        for h in ("x-authorization", "X-Authorization"):
            value = request.headers.get(h)
            if value and len(value) >= 24:
                header_key["XBL_API_KEY"] = value.strip()
                return

    page.on("request", on_request)

    deadline = time.time() + SUCCESS_WAIT_SEC
    last_message = 0.0

    def _accept(candidates: list[str]) -> dict[str, str] | None:
        for cand in candidates:
            if _xbox_key_valid(cand):
                captured["XBL_API_KEY"] = cand
                return captured
        return None

    def _accept_trusted(candidates: list[str]) -> dict[str, str] | None:
        # Candidates pulled from the authenticated /keys endpoint (or sniffed
        # request header) are the user's real keys, so a 429 means valid-but-
        # throttled — accept it rather than looping to the 5-min timeout.
        for cand in candidates:
            if _xbox_key_check(cand) in ("valid", "rate_limited"):
                captured["XBL_API_KEY"] = cand
                return captured
        return None

    while time.time() < deadline:
        # Request-header key is ground truth — prefer it, but still validate.
        if header_key.get("XBL_API_KEY"):
            hit = _accept_trusted([header_key["XBL_API_KEY"]])
            if hit:
                return hit

        url = (page.url or "").lower()

        if _xbl_signed_in(url):
            # Read the key from xbl.io's JSON keys endpoint in the background
            # (no visible navigation, so the user never sees the raw JSON / 404).
            hit = _accept_trusted(_xbl_fetch_keys_json(page))
            if hit:
                return hit
            # Fallback: scrape whatever key is on the current page (still no nav).
            hit = _accept(_xbl_scrape_key_candidates(page))
            if hit:
                return hit

        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit(
                "waiting_for_user",
                {
                    "message": (
                        "Signed in to OpenXBL? If you don't see your API key on the dashboard, "
                        "you may need to verify your phone/email first on xbl.io."
                    )
                    if _xbl_signed_in(url)
                    else (
                        "Click \u201cSign in with Xbox Live\u201d on the xbl.io page to get your "
                        "API key \u2014 we'll capture it automatically."
                    )
                },
            )
        page.wait_for_timeout(int(POLL_SEC * 1000))

    raise RuntimeError(
        "Could not find an OpenXBL API key. Sign in at xbl.io, complete any phone/email "
        "verification, then click Connect again."
    )
