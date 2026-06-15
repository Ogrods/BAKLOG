"""Steam Web API and Store API client with on-disk caching."""

import json
import time
from pathlib import Path

import requests

STORE_DELAY_SEC = 1.5
_STORE_RETRY_BACKOFF = (2, 5, 10)
_RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})


def _get_with_retry(
    url: str,
    params: dict,
    *,
    timeout: int = 30,
    retries: int = 3,
    backoff: tuple[int, ...] = _STORE_RETRY_BACKOFF,
) -> requests.Response:
    """GET with retries on transient network and Steam store errors."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code in _RETRYABLE_HTTP:
                last_exc = requests.HTTPError(
                    f"{resp.status_code} from {url}", response=resp
                )
                if attempt < retries - 1:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
                    continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry loop exited without response")


def _default_steam_cache_dir() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "steam"


class SteamClient:
    def __init__(self, api_key: str, steam_id: str, cache_dir: Path | None = None):
        if cache_dir is None:
            cache_dir = _default_steam_cache_dir()
        self.api_key = api_key
        self.steam_id = steam_id
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_store_call = 0.0

    def _cache_path(self, kind: str, key: str) -> Path:
        return self.cache_dir / kind / f"{key}.json"

    def _read_cache(self, kind: str, key: str) -> dict | None:
        path = self._cache_path(kind, key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _write_cache(self, kind: str, key: str, data: dict) -> None:
        path = self._cache_path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _throttle_store(self) -> None:
        elapsed = time.time() - self._last_store_call
        if elapsed < STORE_DELAY_SEC:
            time.sleep(STORE_DELAY_SEC - elapsed)
        self._last_store_call = time.time()

    def get_owned_games(self) -> list[dict]:
        url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        params = {
            "key": self.api_key,
            "steamid": self.steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        games = data.get("response", {}).get("games", [])
        return games if games else []

    def get_app_details(self, appid: int, refresh: bool = False) -> dict | None:
        cache_key = str(appid)
        if not refresh:
            cached = self._read_cache("appdetails", cache_key)
            if cached is not None:
                return cached

        self._throttle_store()
        url = "https://store.steampowered.com/api/appdetails"
        params = {"appids": appid, "l": "english"}
        resp = _get_with_retry(url, params)
        raw = resp.json()
        entry = raw.get(str(appid), {})
        if not entry.get("success"):
            result = {"success": False, "data": None}
        else:
            result = {"success": True, "data": entry.get("data")}

        self._write_cache("appdetails", cache_key, result)
        return result

    def get_review_summary(self, appid: int, refresh: bool = False) -> dict | None:
        cache_key = str(appid)
        if not refresh:
            cached = self._read_cache("reviews", cache_key)
            if cached is not None:
                return cached

        self._throttle_store()
        url = f"https://store.steampowered.com/appreviews/{appid}"
        params = {
            "json": 1,
            "language": "all",
            "purchase_type": "all",
            "num_per_page": 0,
        }
        resp = _get_with_retry(url, params)
        raw = resp.json()
        summary = raw.get("query_summary", {})
        result = {
            "total_reviews": summary.get("total_reviews", 0),
            "total_positive": summary.get("total_positive", 0),
            "total_negative": summary.get("total_negative", 0),
            "review_score": summary.get("review_score", 0),
            "review_score_desc": summary.get("review_score_desc", ""),
        }
        if result["total_reviews"] > 0:
            result["percent_positive"] = round(
                100 * result["total_positive"] / result["total_reviews"], 1
            )
        else:
            result["percent_positive"] = None

        self._write_cache("reviews", cache_key, result)
        return result
