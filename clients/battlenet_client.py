import re

import browser_cookie3 as bc3
import requests

ACCOUNT_URL = "https://account.battle.net/api/games-and-subs"
_BROWSER_LOADERS = {"edge": bc3.edge, "chrome": bc3.chrome, "brave": bc3.brave, "firefox": bc3.firefox}


class BattleNetAuthError(Exception):
    pass


_SESSION_REJECTED_MSG = "Battle.net rejected the session ({status}). Reconnect Battle.net on the Connections tab (sign in and wait until your Games list loads). CLI fallback: refresh BATTLENET_COOKIE in .env from DevTools (Network → games-and-subs → Cookie header) and run with --browser env."


def probe_session(cookie_header):
    return BattleNetClient(cookie_header).get_raw_account()


class BattleNetClient:
    SUPPORTED_BROWSERS = tuple(_BROWSER_LOADERS.keys())

    def __init__(self, cookie_header, user_agent=None):
        cookie = (cookie_header or "").strip()
        if not cookie:
            raise BattleNetAuthError(
                "No Battle.net session cookie available. Sign in at https://account.battle.net/ in Edge (default), or set BATTLENET_COOKIE in .env as a fallback."
            )
        self.session = requests.Session()
        headers = {
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://account.battle.net/games",
            "User-Agent": user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }
        m = re.search("(?:^|;\\s*)XSRF-TOKEN=([^;]+)", cookie)
        if m:
            headers["X-XSRF-TOKEN"] = m.group(1).strip()
        self.session.headers.update(headers)

    @classmethod
    def from_browser(cls, browser="edge", **kw):
        name = (browser or "edge").strip().lower()
        loader = _BROWSER_LOADERS.get(name)
        if loader is None:
            supported = ", ".join(cls.SUPPORTED_BROWSERS)
            raise BattleNetAuthError(f"Unsupported browser {browser!r}. Choose one of: {supported}, env.")
        try:
            jar = loader(domain_name=".battle.net")
        except Exception as e:
            hint = (
                "Modern Edge/Chrome (v127+) use app-bound cookie encryption that browser-cookie3 can't decrypt on Windows, even from an elevated shell. Recommended: paste the Cookie header into BATTLENET_COOKIE in .env and run with --browser env."
                if name in ("edge", "chrome", "brave")
                else f"Ensure {name} is installed and signed in at account.battle.net."
            )
            raise BattleNetAuthError(f"Could not read {name} cookie jar: {e}\n{hint}") from e
        cookies = [f"{c.name}={c.value}" for c in jar if c.domain and c.domain.lstrip(".").endswith("battle.net")]
        if not cookies:
            raise BattleNetAuthError(
                f"No battle.net cookies found in {name}. Sign in at https://account.battle.net/ in that browser, then retry."
            )
        return cls("; ".join(cookies), **kw)

    def get_raw_account(self):
        resp = self.session.get(ACCOUNT_URL, timeout=30)
        if resp.status_code in (401, 403):
            raise BattleNetAuthError(_SESSION_REJECTED_MSG.format(status=resp.status_code))
        if resp.status_code == 500:
            raise BattleNetAuthError(
                "Battle.net returned 500. This endpoint is unofficial and Blizzard intermittently breaks it; retry later."
            )
        if resp.status_code >= 400:
            raise BattleNetAuthError(f"Battle.net {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise BattleNetAuthError(
                f"Battle.net returned non-JSON ({resp.headers.get('content-type')}). Session likely expired — sign in at account.battle.net in Edge."
            ) from e
