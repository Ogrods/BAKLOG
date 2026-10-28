"""Steam Web API and Store API client with on-disk caching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

STORE_DELAY_SEC = 1.5
# Lighter throttle for review summary fetches (storesearch uses SEARCH_DELAY_SEC).
REVIEW_DELAY_SEC = 0.75
_STORE_RETRY_BACKOFF = (2, 5, 10)
_RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})

# Replaces store.steampowered.com/appreviews/?json=1 (retired ~2026-10-22).
_GET_APP_REVIEWS_URL = (
    "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
)
# IUserReviewsService enums (int values; string names return wrong totals).
_REVIEW_FILTER_HELPFUL = 0
_REVIEW_TYPE_ALL = 0
_PURCHASE_TYPE_ALL = 1


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


def _parse_json_object(resp: requests.Response) -> dict[str, Any]:
    """Parse a JSON object body; raise ValueError on HTML or non-object JSON."""
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.text or ""
    if "html" in ctype or text.lstrip().startswith("<"):
        raise ValueError(
            f"Steam returned HTML instead of JSON from {resp.url} "
            "(review endpoint may be blocked or retired)"
        )
    try:
        raw = resp.json()
    except ValueError as exc:
        raise ValueError(f"Steam returned non-JSON from {resp.url}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Steam JSON was not an object from {resp.url}")
    return raw


def query_summary_present(raw: dict[str, Any]) -> bool:
    """True when the payload includes a query_summary object (even if totals are 0).

    Empty envelopes like ``{"response": {}}`` must not be treated as a confirmed
    zero-review result - caching those would poison later enrich runs.
    """
    envelope = raw.get("response") if isinstance(raw.get("response"), dict) else raw
    if not isinstance(envelope, dict):
        return False
    return isinstance(envelope.get("query_summary"), dict)


def review_summary_from_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize GetAppReviews (or legacy flat) JSON into the on-disk cache shape."""
    envelope = raw.get("response") if isinstance(raw.get("response"), dict) else raw
    summary = envelope.get("query_summary") if isinstance(envelope, dict) else None
    if not isinstance(summary, dict):
        summary = {}
    result: dict[str, Any] = {
        "total_reviews": summary.get("total_reviews", 0) or 0,
        "total_positive": summary.get("total_positive", 0) or 0,
        "total_negative": summary.get("total_negative", 0) or 0,
        "review_score": summary.get("review_score", 0) or 0,
        "review_score_desc": summary.get("review_score_desc", "") or "",
    }
    if result["total_reviews"] > 0:
        result["percent_positive"] = round(
            100 * result["total_positive"] / result["total_reviews"], 1
        )
    else:
        result["percent_positive"] = None
    return result


def fetch_review_summary_payload(
    appid: int,
    *,
    api_key: str = "",
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch public review totals via IUserReviewsService/GetAppReviews."""
    payload: dict[str, Any] = {
        "appid": int(appid),
        "filter": _REVIEW_FILTER_HELPFUL,
        "review_type": _REVIEW_TYPE_ALL,
        "purchase_type": _PURCHASE_TYPE_ALL,
        # Summary fields arrive on the first page; keep the reviews array small.
        "num_per_page": 1,
        "cursor": "*",
        "languages": ["all"],
    }
    params: dict[str, Any] = {"input_json": json.dumps(payload, separators=(",", ":"))}
    if api_key:
        params["key"] = api_key
    resp = _get_with_retry(_GET_APP_REVIEWS_URL, params, timeout=timeout)
    return _parse_json_object(resp)


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
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt / truncated cache: treat as miss so the next fetch can heal.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _write_cache(self, kind: str, key: str, data: dict) -> None:
        path = self._cache_path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _throttle_store(self, delay: float | None = None) -> None:
        min_gap = STORE_DELAY_SEC if delay is None else delay
        elapsed = time.time() - self._last_store_call
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
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

    def get_app_details_batch(
        self, appids: list[int], refresh: bool = False
    ) -> dict[int, dict | None]:
        """Fetch appdetails for many appids; one store request per appid.

        Steam's store API returns 400 when multiple comma-separated appids are
        sent without a narrow filters= price_overview-only mode, so batching
        HTTP calls is not viable for full app metadata.
        """
        results: dict[int, dict | None] = {}
        for appid in appids:
            cache_key = str(appid)
            if not refresh:
                cached = self._read_cache("appdetails", cache_key)
                if cached is not None:
                    results[appid] = cached
                    continue
            results[appid] = self.get_app_details(appid, refresh=refresh)
        return results

    def get_review_summary(self, appid: int, refresh: bool = False) -> dict | None:
        cache_key = str(appid)
        if not refresh:
            cached = self._read_cache("reviews", cache_key)
            if cached is not None:
                return cached

        self._throttle_store(REVIEW_DELAY_SEC)
        raw = fetch_review_summary_payload(appid, api_key=self.api_key or "")
        result = review_summary_from_payload(raw)
        # Only persist confirmed summaries. Empty envelopes must not poison cache.
        if query_summary_present(raw):
            self._write_cache("reviews", cache_key, result)
        return result
