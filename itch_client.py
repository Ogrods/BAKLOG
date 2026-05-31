"""itch.io personal API client.

Uses an API key from https://itch.io/user/settings/api-keys with the
endpoint base ``https://itch.io/api/1/<KEY>/...``.

Only the read endpoints we need:

- ``my-owned-keys?page=N`` — paginated list of games the signed-in user owns
  (purchases + claimed bundle items + free downloads they've grabbed).
- ``game/<id>`` — extra metadata for a single game.

itch.io's API is lightly documented (see
https://itch.io/docs/api/serverside). Rate limits are not published; we
self-throttle to be polite.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://itch.io/api/1"
DEFAULT_PAGE_SIZE_FALLBACK = 50  # itch may return up to 50 keys per page
REQUEST_DELAY_SEC = 0.4


class ItchAuthError(Exception):
    """Raised when the itch.io API rejects the supplied key."""


class ItchApiError(Exception):
    """Raised on transport or unexpected response errors."""


class ItchClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path = Path("cache/itch"),
        timeout: int = 30,
    ) -> None:
        if not api_key:
            raise ItchAuthError("Set ITCH_API_KEY in .env (https://itch.io/user/settings/api-keys)")
        self.api_key = api_key.strip()
        self.cache_dir = cache_dir
        (self.cache_dir / "games").mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "steam-backlog/1.0 (+itch)"

    # ---- transport ----

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_call = time.time()

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._throttle()
        url = f"{BASE_URL}/{self.api_key}/{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise ItchApiError(f"itch.io request failed: {e}") from e
        if resp.status_code in (401, 403):
            raise ItchAuthError("itch.io rejected the API key (401/403). Regenerate at https://itch.io/user/settings/api-keys")
        if resp.status_code >= 400:
            raise ItchApiError(f"itch.io HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise ItchApiError(f"itch.io returned non-JSON: {e}") from e
        if isinstance(data, dict) and data.get("errors"):
            raise ItchApiError(f"itch.io error: {data['errors']}")
        return data

    # ---- endpoints ----

    def me(self) -> dict:
        return self._get("me").get("user", {})

    def owned_keys_page(self, page: int) -> list[dict]:
        """One page of ``download_keys``. Empty list means the end."""
        data = self._get("my-owned-keys", {"page": page})
        keys = data.get("owned_keys") or data.get("download_keys") or []
        if not isinstance(keys, list):
            return []
        return keys

    def all_owned_keys(self) -> list[dict]:
        """Walk every page until itch returns an empty result."""
        out: list[dict] = []
        seen_ids: set[int] = set()
        page = 1
        while True:
            chunk = self.owned_keys_page(page)
            if not chunk:
                break
            new_in_page = 0
            for entry in chunk:
                game = entry.get("game") or {}
                gid = game.get("id")
                if gid is None or gid in seen_ids:
                    continue
                seen_ids.add(gid)
                out.append(entry)
                new_in_page += 1
            # Stop if the API returns a page that's all duplicates (defensive).
            if new_in_page == 0:
                break
            print(
                f"  · itch owned-keys page {page}: {len(out)} games so far",
                flush=True,
            )
            page += 1
            if page > 200:  # hard safety cap (~10k games)
                break
        return out

    def game(self, game_id: int) -> dict:
        cache_path = self.cache_dir / "games" / f"{game_id}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        data = self._get(f"game/{game_id}")
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data


__all__ = ["ItchClient", "ItchAuthError", "ItchApiError"]
