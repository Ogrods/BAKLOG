"""Backfill steam_review_percent for non-Steam library rows.

For each game in games_gog.json / games_epic.json / games_psn.json that lacks
a steam_review_percent, search Steam's store for a matching title, then pull
the review summary. Saves a small mapping file so repeat runs are fast.
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

from steam_client import SteamClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAPPING_FILE = Path("cache/steam_review_map.json")
SEARCH_DELAY_SEC = 1.0
SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}

STORE_FILES = [
    ("games_gog.json", "gog"),
    ("games_epic.json", "epic"),
    ("games_psn.json", "psn"),
]


def normalize(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[\u2122\u00ae\u00a9]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|"
        r"of the year|game of the year|special|standard|deluxe|collection|"
        r"anthology|pack|the|hd|remake)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def load_mapping() -> dict:
    if MAPPING_FILE.exists():
        try:
            return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_mapping(mapping: dict) -> None:
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def steam_search(name: str) -> int | None:
    """Return the most likely Steam appid for a game title, or None."""
    time.sleep(SEARCH_DELAY_SEC)
    try:
        r = requests.get(
            SEARCH_URL,
            params={"term": name, "l": "english", "cc": "us"},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items") or []
    except Exception as e:
        print(f"  search error: {e}")
        return None
    if not items:
        return None
    target = normalize(name)
    for item in items:
        if normalize(item.get("name", "")) == target:
            return int(item["id"])
    # fall back to first result if its title is "close enough"
    first = items[0]
    first_norm = normalize(first.get("name", ""))
    if first_norm and (first_norm in target or target in first_norm):
        return int(first["id"])
    return None


def steam_appids_by_id() -> set[int]:
    try:
        data = json.loads(Path("games_steam.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {g["id"] for g in data.get("games", [])}


def main() -> int:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    steam_id = os.getenv("STEAM_ID", "").strip()
    if not api_key or not steam_id:
        print("STEAM_API_KEY/STEAM_ID required in .env", file=sys.stderr)
        return 1

    steam = SteamClient(api_key=api_key, steam_id=steam_id)
    mapping = load_mapping()
    owned_ids = steam_appids_by_id()

    for filename, store in STORE_FILES:
        path = Path(filename)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        print(f"\n=== {filename} ({len(games)} games) ===")
        updated = 0
        for i, g in enumerate(games, 1):
            if g.get("steam_review_percent") is not None:
                continue
            key = f"{store}:{g['id']}"
            cached_appid = mapping.get(key)

            if cached_appid == 0:
                continue
            appid: int | None = cached_appid

            if appid is None:
                appid = steam_search(g["name"])
                mapping[key] = appid if appid else 0
                if i % 10 == 0:
                    save_mapping(mapping)

            if not appid:
                continue

            if appid in owned_ids:
                pass

            try:
                reviews = steam.get_review_summary(appid)
            except Exception as e:
                print(f"  reviews error for {g['name']} ({appid}): {e}")
                continue
            if not reviews or reviews.get("percent_positive") is None:
                continue
            g["steam_review_percent"] = reviews["percent_positive"]
            g["steam_review_count"] = reviews.get("total_reviews")
            g["steam_review_desc"] = reviews.get("review_score_desc")
            updated += 1
            if updated % 25 == 0:
                print(f"  [{i}/{len(games)}] {updated} updated so far ({g['name']} -> {reviews['percent_positive']}%)")

        data["game_count"] = len(games)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  updated {updated} rows in {filename}")
        save_mapping(mapping)

    save_mapping(mapping)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
