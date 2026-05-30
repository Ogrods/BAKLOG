"""IsThereAnyDeal API client. Requires free API key from isthereanydeal.com."""

import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://api.isthereanydeal.com"
REQUEST_DELAY_SEC = 0.35


class ItadError(Exception):
    pass


class ItadClient:
    def __init__(self, api_key: str, country: str = "US", cache_dir: Path = Path("cache/itad")):
        self.api_key = api_key
        self.country = country
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "steam-backlog/1.0"

    def _throttle(self) -> None:
        elapsed = time.time() - self._last
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last = time.time()

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._throttle()
        p = {"key": self.api_key, **(params or {})}
        resp = self.session.get(f"{BASE}/{path}", params=p, timeout=30)
        if resp.status_code == 401:
            raise ItadError("Invalid ITAD_API_KEY")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: list | dict, params: dict | None = None) -> list | dict:
        self._throttle()
        p = {"key": self.api_key, **(params or {})}
        resp = self.session.post(f"{BASE}/{path}", params=p, json=body, timeout=60)
        if resp.status_code == 401:
            raise ItadError("Invalid ITAD_API_KEY")
        resp.raise_for_status()
        return resp.json()

    def lookup_title(self, title: str, appid: int | None = None) -> str | None:
        """Return ITAD game id (UUID) for a title, or None."""
        cache_key = f"{appid}:{title}" if appid else title
        cache_path = self.cache_dir / "lookup" / f"{quote(cache_key, safe='')[:120]}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached.get("id")

        params: dict = {}
        if appid:
            params["appid"] = appid
        else:
            params["title"] = title

        try:
            data = self._get("games/lookup/v1", params)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                data = {"found": False}
            else:
                raise

        game_id = None
        if data.get("found") and data.get("game"):
            game_id = data["game"].get("id")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"id": game_id}, ensure_ascii=False), encoding="utf-8")
        return game_id

    def prices_for_ids(self, game_ids: list[str]) -> dict[str, dict]:
        """Batch current prices. Returns game id -> best deal info."""
        if not game_ids:
            return {}
        out: dict[str, dict] = {}
        chunk_size = 200
        for i in range(0, len(game_ids), chunk_size):
            chunk = game_ids[i : i + chunk_size]
            entries = self._post("games/prices/v3", chunk, {"country": self.country})
            if not isinstance(entries, list):
                continue
            for entry in entries:
                gid = entry.get("id")
                deals = entry.get("deals") or []
                if not gid or not deals:
                    continue
                best = min(deals, key=lambda d: d.get("price", {}).get("amount", 999999))
                price = best.get("price") or {}
                regular = best.get("regular") or {}
                hist = entry.get("historyLow") or {}
                out[gid] = {
                    "shop": (best.get("shop") or {}).get("name"),
                    "price": price.get("amount"),
                    "price_str": f"${price.get('amount', 0):.2f}" if price.get("amount") is not None else None,
                    "regular": regular.get("amount"),
                    "cut": best.get("cut", 0),
                    "url": best.get("url"),
                    "history_low_all": (hist.get("all") or {}).get("amount"),
                    "is_historical_low": price.get("amount") is not None
                    and hist.get("all", {}).get("amount") is not None
                    and price.get("amount") <= hist.get("all", {}).get("amount") + 0.01,
                }
        return out

    # Back-compat alias used by fetch_itad.py
    def prices_for_plains(self, plains: list[str]) -> dict[str, dict]:
        return self.prices_for_ids(plains)
