"""Battle.net account scraper via the unofficial games-and-subs JSON endpoint.

There is no public Blizzard API for "list every game I own". The endpoint that
powers account.battle.net/games returns the data we want, but requires being
logged in. Auto-reading Edge/Chrome cookies usually fails on Windows because of
app-bound encryption (v127+) — even with admin. The recommended path is to
paste the Cookie header into BATTLENET_COOKIE in .env and run with
`--browser env`. The browser jar loaders are kept for Firefox and for users
who manage to read Edge cookies on their machine.
"""

from __future__ import annotations

import re
from typing import ClassVar
from urllib.parse import unquote

import requests

ACCOUNT_URL = "https://account.battle.net/api/games-and-subs"

# Names only — browser_cookie3 is imported inside from_browser() so
# probe_session / BattleNetClient(cookie) work in frozen builds without it.
_BROWSER_LOADER_NAMES: tuple[str, ...] = ("edge", "chrome", "brave", "firefox")


class BattleNetAuthError(Exception):
    pass


_SESSION_REJECTED_MSG = (
    "Battle.net rejected the session ({status}). Reconnect Battle.net on the "
    "Connections tab (sign in and wait until your Games list loads). "
    "CLI fallback: refresh BATTLENET_COOKIE in .env from DevTools "
    "(Network → games-and-subs → Cookie header) and run with --browser env."
)


def probe_session(cookie_header: str) -> dict:
    """Verify the cookie can read the games-and-subs API; raise on 401/403."""
    return BattleNetClient(cookie_header).get_raw_account()


class BattleNetClient:
    SUPPORTED_BROWSERS: ClassVar[tuple[str, ...]] = _BROWSER_LOADER_NAMES

    def __init__(self, cookie_header: str, user_agent: str | None = None):
        cookie = (cookie_header or "").strip()
        if not cookie:
            raise BattleNetAuthError(
                "No Battle.net session cookie available. Sign in at "
                "https://account.battle.net/ in Edge (default), or set "
                "BATTLENET_COOKIE in .env as a fallback."
            )
        self.session = requests.Session()
        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://account.battle.net/games",
            "User-Agent": user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }
        # Battle.net uses double-submit CSRF: token in cookie XSRF-TOKEN must
        # be echoed back as the X-XSRF-TOKEN header for state-aware requests.
        # Cookie values are often URL-encoded; the header expects the decoded form.
        m = re.search(r"(?:^|;\s*)XSRF-TOKEN=([^;]+)", cookie)
        if m:
            headers["X-XSRF-TOKEN"] = unquote(m.group(1).strip())
        self.session.headers.update(headers)

    @classmethod
    def from_browser(cls, browser: str = "edge", **kw) -> BattleNetClient:
        try:
            import browser_cookie3 as bc3
        except Exception as e:  # noqa: BLE001
            raise BattleNetAuthError(
                f"browser_cookie3 is unavailable ({e}). Paste the Cookie header "
                "into BATTLENET_COOKIE in .env and run with --browser env, or use "
                "Connect on the Connections tab."
            ) from e
        loaders = {
            "edge": bc3.edge,
            "chrome": bc3.chrome,
            "brave": bc3.brave,
            "firefox": bc3.firefox,
        }
        name = (browser or "edge").strip().lower()
        loader = loaders.get(name)
        if loader is None:
            supported = ", ".join(cls.SUPPORTED_BROWSERS)
            raise BattleNetAuthError(
                f"Unsupported browser {browser!r}. Choose one of: {supported}, env."
            )
        try:
            jar = loader(domain_name=".battle.net")
        except Exception as e:
            hint = (
                "Modern Edge/Chrome (v127+) use app-bound cookie encryption that "
                "browser-cookie3 can't decrypt on Windows, even from an elevated "
                "shell. Recommended: paste the Cookie header into "
                "BATTLENET_COOKIE in .env and run with --browser env."
                if name in ("edge", "chrome", "brave")
                else f"Ensure {name} is installed and signed in at account.battle.net."
            )
            raise BattleNetAuthError(
                f"Could not read {name} cookie jar: {e}\n{hint}"
            ) from e
        cookies = [
            f"{c.name}={c.value}"
            for c in jar
            if c.domain and c.domain.lstrip(".").endswith("battle.net")
        ]
        if not cookies:
            raise BattleNetAuthError(
                f"No battle.net cookies found in {name}. Sign in at "
                "https://account.battle.net/ in that browser, then retry."
            )
        return cls("; ".join(cookies), **kw)

    def get_raw_account(self) -> dict:
        resp = self.session.get(ACCOUNT_URL, timeout=30)
        if resp.status_code in (401, 403):
            raise BattleNetAuthError(
                _SESSION_REJECTED_MSG.format(status=resp.status_code)
            )
        if resp.status_code == 500:
            raise BattleNetAuthError(
                "Battle.net returned 500. This endpoint is unofficial and Blizzard "
                "intermittently breaks it; retry later."
            )
        if resp.status_code >= 400:
            raise BattleNetAuthError(f"Battle.net {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise BattleNetAuthError(
                f"Battle.net returned non-JSON ({resp.headers.get('content-type')}). "
                "Session likely expired — sign in at account.battle.net in Edge."
            ) from e
