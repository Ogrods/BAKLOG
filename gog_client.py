"""GOG embed.gog.com client with on-disk caching."""

import json
import time
from pathlib import Path

import requests

CACHE_DIR = Path("cache/gog")
REQUEST_DELAY_SEC = 1.0
EMBED_BASE = "https://embed.gog.com"


class GogAuthError(Exception):
    """Session cookie invalid or expired."""


class GogClient:
    def __init__(self, gog_al: str, cache_dir: Path = CACHE_DIR):
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

    def _read_cache(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _write_cache(self, key: str, data: dict) -> None:
        self._cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def _get(self, path: str, refresh: bool = False, cache_key: str | None = None) -> dict:
        ck = cache_key or path.replace("/", "_")
        if not refresh:
            cached = self._read_cache(ck)
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
        data = self._get("/user/data/games", cache_key="user_data_games")
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
        return self._get(path, refresh=refresh, cache_key=f"filtered_products_p{page}")

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
        )
