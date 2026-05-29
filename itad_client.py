"""IsThereAnyDeal API client (v01). Requires free API key from isthereanydeal.com."""

import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://api.isthereanydeal.com/v01"
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

    def lookup_title(self, title: str) -> str | None:
        """Return ITAD ``plain`` id for a game title, or None."""
        cache_path = self.cache_dir / "lookup" / f"{quote(title, safe='')[:120]}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached.get("plain")

        data = self._get("game/lookup/v1", {"title": title})
        plain = None
        for item in data.get("data", {}).get(title, []) or []:
            if item.get("title", "").lower() == title.lower():
                plain = item.get("plain")
                break
        if not plain:
            items = data.get("data", {}).get(title, []) or []
            if items:
                plain = items[0].get("plain")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"plain": plain}, ensure_ascii=False), encoding="utf-8")
        return plain

    def prices_for_plains(self, plains: list[str]) -> dict[str, dict]:
        """Batch current prices. Returns plain -> best deal info."""
        if not plains:
            return {}
        out: dict[str, dict] = {}
        chunk_size = 200
        for i in range(0, len(plains), chunk_size):
            chunk = plains[i : i + chunk_size]
            params = [("plains", p) for p in chunk]
            params.append(("country", self.country))
            self._throttle()
            resp = self.session.get(
                f"{BASE}/game/prices/",
                params=[("key", self.api_key)] + params,
                timeout=60,
            )
            resp.raise_for_status()
            for entry in resp.json().get("data", {}).get("list", []) or []:
                plain = entry.get("id")
                deals = entry.get("deals") or []
                if not plain or not deals:
                    continue
                best = min(deals, key=lambda d: d.get("price", {}).get("amount", 999999))
                price = best.get("price") or {}
                regular = best.get("regular") or {}
                hist = entry.get("historyLow") or {}
                out[plain] = {
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
