"""EA App (Juno) library client — replays your own ea.com web session.

This client does **not** impersonate EA's desktop app. It carries no baked-in
client secret and performs no first-party OAuth flow. Instead it reuses the
Bearer token that ea.com's own website obtains for the signed-in user (sniffed
from your saved browser profile in fetch_ea.py) and replays the website's own
GraphQL query against the same endpoint your browser already calls. In other
words: the same traffic you could generate yourself with DevTools open on
ea.com, automated locally on your machine.
"""

from __future__ import annotations

import json
import time
from urllib.parse import quote

import requests

GRAPHQL_URL = "https://service-aggregation-layer.juno.ea.com/graphql"
# Persisted-query identifiers used by the ea.com web app (Juno GraphQL APQ).
# getPreloadedOwnedGames hash matches the live ea.com deals/library page (2025+).
OWNED_GAMES_HASH = "779f1cd1355699752e20c0b3877847f4e3010ef5de131c248e98f8eff84f0718"
PLAY_TIMES_HASH = "3f09b35e06b75c74d8ec3e520a598ebb5e2992b1e1268b6dd3b8ed99b9fafb29"

REAL_OWNERSHIP = frozenset({
    "UNKNOWN",
    "ASSOCIATION",
    "PURCHASE",
    "REDEMPTION",
    "GIFT_RECEIPT",
    "ENTITLEMENT_GRANT",
    "DIRECT_ENTITLEMENT",
    "PRE_ORDER_PURCHASE",
    "STEAM",
    "EPIC",
})
EA_PLAY_OWNERSHIP = frozenset({
    "VAULT",
    "STEAM_VAULT",
    "STEAM_SUBSCRIPTION",
    "EPIC_VAULT",
    "EPIC_SUBSCRIPTION",
})
XGP_ONLY = frozenset({"XGP_VAULT"})

REQUEST_DELAY_SEC = 0.15


class EaAuthError(Exception):
    pass


class EaCaptureError(Exception):
    """Logged-in session present but Bearer token could not be captured."""


def _persisted_url(operation: str, variables: dict, sha256_hash: str) -> str:
    variables_json = json.dumps(variables, separators=(",", ":"))
    ext = json.dumps(
        {"persistedQuery": {"version": 1, "sha256Hash": sha256_hash}},
        separators=(",", ":"),
    )
    return (
        f"{GRAPHQL_URL}?operationName={quote(operation)}"
        f"&variables={quote(variables_json)}"
        f"&extensions={quote(ext)}"
    )


class EaClient:
    def __init__(
        self,
        access_token: str,
        cookies: list[dict] | dict | None = None,
    ) -> None:
        token = (access_token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise EaAuthError(
                "No EA web session token — connect EA App on the Connections page first."
            )
        self._access_token = token
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            }
        )
        if isinstance(cookies, dict):
            self.session.cookies.update(cookies)
        elif isinstance(cookies, list):
            for c in cookies:
                name = c.get("name")
                value = c.get("value")
                if name and value is not None:
                    self.session.cookies.set(name, value)

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_request = time.time()

    def _graphql_get(self, operation: str, variables: dict, sha256_hash: str) -> dict:
        self._throttle()
        url = _persisted_url(operation, variables, sha256_hash)
        resp = self.session.get(url, timeout=60)
        if resp.status_code in (401, 403):
            raise EaAuthError(f"EA GraphQL unauthorized ({resp.status_code}) — reconnect EA App.")
        if resp.status_code >= 400:
            raise EaAuthError(f"EA GraphQL HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if data.get("errors"):
            raise EaAuthError(f"EA GraphQL errors: {data['errors'][:1]}")
        return data

    def probe_owned_games(self) -> None:
        """Single-page owned-games query to verify the Bearer token."""
        self._graphql_get(
            "getPreloadedOwnedGames",
            {
                "isMac": False,
                "addFieldsToPreloadGames": False,
                "locale": "en",
                "limit": 1,
                "next": "0",
                "type": ["DIGITAL_FULL_GAME", "PACKAGED_FULL_GAME"],
                "entitlementEnabled": True,
                "storefronts": ["EA", "STEAM", "EPIC"],
                "ownershipMethods": sorted(REAL_OWNERSHIP | EA_PLAY_OWNERSHIP | XGP_ONLY),
                "platforms": ["PC"],
            },
            OWNED_GAMES_HASH,
        )

    def get_owned_games(self) -> list[dict]:
        out: list[dict] = []
        offset = "0"
        page = 0
        while True:
            root = self._graphql_get(
                "getPreloadedOwnedGames",
                {
                    "isMac": False,
                    "addFieldsToPreloadGames": True,
                    "locale": "en",
                    "limit": 500,
                    "next": offset,
                    "type": ["DIGITAL_FULL_GAME", "PACKAGED_FULL_GAME"],
                    "entitlementEnabled": True,
                    "storefronts": ["EA", "STEAM", "EPIC"],
                    "ownershipMethods": sorted(REAL_OWNERSHIP | EA_PLAY_OWNERSHIP | XGP_ONLY),
                    "platforms": ["PC"],
                },
                OWNED_GAMES_HASH,
            )
            owned = (root.get("data") or {}).get("me", {}).get("ownedGameProducts") or {}
            items = owned.get("items") or []
            if isinstance(items, list):
                out.extend(i for i in items if isinstance(i, dict))
            offset = owned.get("next")
            if not offset:
                break
            page += 1
        return out

    def get_play_times(self, slugs: list[str]) -> list[dict]:
        if not slugs:
            return []
        root = self._graphql_get(
            "GetGamePlayTimes",
            {"gameSlugs": slugs},
            PLAY_TIMES_HASH,
        )
        recent = (root.get("data") or {}).get("me", {}).get("recentGames") or {}
        items = recent.get("items") or []
        return [i for i in items if isinstance(i, dict)]
