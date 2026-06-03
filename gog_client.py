"""GOG embed.gog.com client with on-disk caching."""

import json
import time
from pathlib import Path

import requests

REQUEST_DELAY_SEC = 1.0


def _default_gog_cache_dir() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "gog"
EMBED_BASE = "https://embed.gog.com"

# Per-endpoint cache TTLs. `None` means "cache forever" (legacy behaviour),
# `0` forces a re-fetch every call. Tuned to balance speed against the
# staleness bugs we've actually hit:
#   - user-state lists (owned/wishlist IDs) are tiny and change whenever the
#     user clicks a heart on gog.com -- never trust cached results.
#   - paginated owned library metadata is slow to re-fetch but only changes
#     when you buy a game; refresh once a day.
#   - per-product detail is essentially immutable once published.
USER_STATE_TTL = 0
LIBRARY_TTL = 24 * 60 * 60
DETAILS_TTL = None


class GogAuthError(Exception):
    """Session cookie invalid or expired."""


class GogClient:
    def __init__(self, gog_al: str, cache_dir: Path | None = None):
        if cache_dir is None:
            cache_dir = _default_gog_cache_dir()
        self.session = requests.Session()
        self.session.cookies.set("gog-al", gog_al, domain=".gog.com")
        self.session.headers.update(
            {
                "User-Agent": "steam-backlog/1.0",
                "Accept": "application/json",
            }
        )
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_request = time.time()

    def _cache_path(self, key: str) -> Path:
        safe = key.replace("/", "_")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, key: str, max_age_seconds: float | None = None) -> dict | None:
        """Return the cached payload for ``key`` if it's still considered fresh.

        ``max_age_seconds`` semantics:
            - ``None``: cache never expires (legacy behaviour).
            - ``0``: cache is always stale; callers should re-fetch.
            - Otherwise: payload is fresh iff it was written within that many
              seconds ago.
        """
        path = self._cache_path(key)
        if not path.exists():
            return None
        if max_age_seconds is not None:
            age = time.time() - path.stat().st_mtime
            if age >= max_age_seconds:
                return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key: str, data: dict) -> None:
        self._cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def _get(
        self,
        path: str,
        refresh: bool = False,
        cache_key: str | None = None,
        max_age_seconds: float | None = None,
    ) -> dict:
        ck = cache_key or path.replace("/", "_")
        if not refresh:
            cached = self._read_cache(ck, max_age_seconds=max_age_seconds)
            if cached is not None:
                return cached

        self._throttle()
        url = f"{EMBED_BASE}{path}"
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 401:
            raise GogAuthError(
                "GOG session expired. Sign in at gog.com and update GOG_AL in .env."
            )
        resp.raise_for_status()
        data = resp.json()
        self._write_cache(ck, data)
        return data

    def validate_session(self) -> bool:
        self._throttle()
        resp = self.session.get(f"{EMBED_BASE}/userData.json", timeout=30)
        if resp.status_code == 401:
            raise GogAuthError(
                "GOG session expired. Sign in at gog.com and update GOG_AL in .env."
            )
        resp.raise_for_status()
        return True

    def get_owned_game_ids(self) -> list[int]:
        data = self._get(
            "/user/data/games",
            cache_key="user_data_games",
            max_age_seconds=USER_STATE_TTL,
        )
        owned = data.get("owned", data.get("games", []))
        ids: list[int] = []
        for item in owned:
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, dict):
                pid = item.get("gameId") or item.get("id") or item.get("productId")
                if pid is not None:
                    ids.append(int(pid))
        return ids

    def get_filtered_products(self, page: int = 1, refresh: bool = False) -> dict:
        path = f"/account/getFilteredProducts?mediaType=1&sortBy=title&page={page}"
        return self._get(
            path,
            refresh=refresh,
            cache_key=f"filtered_products_p{page}",
            max_age_seconds=LIBRARY_TTL,
        )

    def get_all_filtered_products(self, refresh: bool = False) -> list[dict]:
        products: list[dict] = []
        page = 1
        while True:
            data = self.get_filtered_products(page, refresh=refresh)
            batch = data.get("products", [])
            if not batch:
                break
            products.extend(batch)
            total_pages = data.get("totalPages") or data.get("total_pages") or 1
            if page >= total_pages:
                break
            page += 1
        return products

    def get_product_details(self, product_id: int, refresh: bool = False) -> dict:
        return self._get(
            f"/account/gameDetails/{product_id}.json",
            refresh=refresh,
            cache_key=f"details_{product_id}",
            max_age_seconds=DETAILS_TTL,
        )
