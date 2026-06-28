import json
import time

import requests

from fetchers._progress import HeartbeatTimer, heartbeat, progress_line

REQUEST_DELAY_SEC = 1.0


def _default_gog_cache_dir():
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "gog"


EMBED_BASE = "https://embed.gog.com"
USER_STATE_TTL = 0
LIBRARY_TTL = 24 * 60 * 60
DETAILS_TTL = None
GOG_AUTH_MESSAGE = "GOG session rejected (expired or blocked). Reconnect GOG on the Connections page, or run with --source local if GOG Galaxy is installed."
_GOG_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class GogAuthError(Exception):
    pass


class GogClient:
    def __init__(self, gog_al, cache_dir=None):
        if cache_dir is None:
            cache_dir = _default_gog_cache_dir()
        self.session = requests.Session()
        self.session.cookies.set("gog-al", gog_al, domain=".gog.com")
        self.session.headers.update(
            {
                "User-Agent": _GOG_BROWSER_UA,
                "Accept": "application/json",
                "Referer": "https://www.gog.com/",
                "Origin": "https://www.gog.com",
            }
        )
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_request = time.time()

    def _cache_path(self, key):
        safe = key.replace("/", "_")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, key, max_age_seconds=None):
        path = self._cache_path(key)
        if not path.exists():
            return None
        if max_age_seconds is not None:
            if max_age_seconds <= 0:
                return None
            age = time.time() - path.stat().st_mtime
            if age >= max_age_seconds:
                return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, key, data):
        self._cache_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _raise_if_auth_error(resp):
        if resp.status_code in (401, 403):
            raise GogAuthError(GOG_AUTH_MESSAGE)

    def _get(self, path, refresh=False, cache_key=None, max_age_seconds=None):
        ck = cache_key or path.replace("/", "_")
        if not refresh:
            cached = self._read_cache(ck, max_age_seconds=max_age_seconds)
            if cached is not None:
                return cached
        self._throttle()
        url = f"{EMBED_BASE}{path}"
        resp = self.session.get(url, timeout=30)
        self._raise_if_auth_error(resp)
        resp.raise_for_status()
        data = resp.json()
        self._write_cache(ck, data)
        return data

    def validate_session(self):
        self._throttle()
        resp = self.session.get(f"{EMBED_BASE}/userData.json", timeout=30)
        if resp.status_code not in (401, 403):
            resp.raise_for_status()
        try:
            self.get_filtered_products(page=1, refresh=True)
            return True
        except GogAuthError:
            try:
                self.get_owned_game_ids()
                return True
            except GogAuthError:
                raise GogAuthError(GOG_AUTH_MESSAGE) from None

    def get_owned_game_ids(self):
        data = self._get("/user/data/games", cache_key="user_data_games", max_age_seconds=USER_STATE_TTL)
        owned = data.get("owned", data.get("games", []))
        ids = []
        for item in owned:
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, dict):
                pid = item.get("gameId") or item.get("id") or item.get("productId")
                if pid is not None:
                    ids.append(int(pid))
        return ids

    def get_filtered_products(self, page=1, refresh=False):
        path = f"/account/getFilteredProducts?mediaType=1&sortBy=title&page={page}"
        return self._get(path, refresh=refresh, cache_key=f"filtered_products_p{page}", max_age_seconds=LIBRARY_TTL)

    def get_all_filtered_products(self, refresh=False):
        hb = HeartbeatTimer(interval=25.0)
        products = []
        page = 1
        total_pages = 1
        while True:
            hb.tick_progress(page, total_pages, "GOG library pages", f"{len(products)} products")
            data = self.get_filtered_products(page, refresh=refresh)
            batch = data.get("products", [])
            if not batch:
                break
            products.extend(batch)
            total_pages = data.get("totalPages") or data.get("total_pages") or page
            if page >= total_pages:
                break
            page += 1
        heartbeat(progress_line(page, total_pages, "GOG library", f"{len(products)} products"))
        return products

    def get_product_details(self, product_id, refresh=False):
        return self._get(
            f"/account/gameDetails/{product_id}.json",
            refresh=refresh,
            cache_key=f"details_{product_id}",
            max_age_seconds=DETAILS_TTL,
        )
