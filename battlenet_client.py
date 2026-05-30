"""Battle.net account scraper via the unofficial games-and-subs JSON endpoint.

There is no public Blizzard API for "list every game I own". The endpoint that
powers account.battle.net/games returns the data we want, but requires being
logged in - we replay the session by sending the full Cookie header copied from
DevTools.
"""

from __future__ import annotations

import re

import requests

ACCOUNT_URL = "https://account.battle.net/api/games-and-subs"


class BattleNetAuthError(Exception):
    pass


class BattleNetClient:
    def __init__(self, cookie_header: str, user_agent: str | None = None):
        cookie = (cookie_header or "").strip()
        if not cookie:
            raise BattleNetAuthError(
                "Set BATTLENET_COOKIE in .env (copy the Cookie header from "
                "account.battle.net DevTools → Network → games-and-subs request)."
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
        m = re.search(r"(?:^|;\s*)XSRF-TOKEN=([^;]+)", cookie)
        if m:
            headers["X-XSRF-TOKEN"] = m.group(1).strip()
        self.session.headers.update(headers)

    def get_raw_account(self) -> dict:
        resp = self.session.get(ACCOUNT_URL, timeout=30)
        if resp.status_code in (401, 403):
            raise BattleNetAuthError(
                f"Battle.net rejected the cookie ({resp.status_code}). Sign in again at "
                "account.battle.net and copy a fresh Cookie header into BATTLENET_COOKIE."
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
                "Cookie likely invalid - re-copy from DevTools."
            ) from e
