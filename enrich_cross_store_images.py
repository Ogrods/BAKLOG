#!/usr/bin/env python3
"""Backfill header/library images for non-Steam rows via Steam store search."""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}
SEARCH_DELAY = 0.4
WORKERS = 4

STORE_FILES = [
    Path("games_gog.json"),
    Path("games_psn.json"),
    Path("games_epic.json"),
    Path("games_amazon.json"),
]


def normalize(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[\u2122\u00ae\u00a9]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def steam_search_appid(name: str) -> int | None:
    time.sleep(SEARCH_DELAY)
    try:
        r = requests.get(
            SEARCH_URL,
            params={"term": name, "l": "english", "cc": "US"},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items") or []
    except Exception:
        return None
    if not items:
        return None
    target = normalize(name)
    for item in items:
        if normalize(item.get("name", "")) == target:
            return int(item["id"])
    return int(items[0]["id"])


def image_urls(appid: int) -> tuple[str, str]:
    base = "https://cdn.akamai.steamstatic.com/steam/apps"
    return (
        f"{base}/{appid}/header.jpg",
        f"{base}/{appid}/library_600x900_2x.jpg",
    )


def needs_images(g: dict) -> bool:
    lib = g.get("library_image") or ""
    hdr = g.get("header_image") or ""
    if not lib and not hdr:
        return True
    if lib.endswith(".eprt") or hdr.endswith(".eprt"):
        return True
    return False


def process_game(g: dict) -> dict | None:
    if not needs_images(g):
        return None
    appid = g.get("steam_appid")
    if not appid:
        appid = steam_search_appid(g.get("name", ""))
    if not appid:
        return None
    header, library = image_urls(appid)
    g = dict(g)
    g["header_image"] = header
    g["library_image"] = library
    g["steam_appid"] = appid
    g["image_source"] = "steam_search"
    return g


def main() -> int:
    updated = 0
    for path in STORE_FILES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        todo = [g for g in games if needs_images(g)]
        if not todo:
            print(f"{path.name}: nothing to enrich")
            continue
        print(f"{path.name}: enriching {len(todo)} games...")
        by_id = {g["id"]: g for g in games}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process_game, g): g["id"] for g in todo}
            for fut in as_completed(futures):
                gid = futures[fut]
                try:
                    new_g = fut.result()
                except Exception as e:
                    print(f"  {gid}: {e}")
                    continue
                if new_g:
                    by_id[gid] = new_g
                    updated += 1
                    print(f"  + {new_g.get('name', gid)}")
        data["games"] = list(by_id.values())
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nUpdated {updated} games with Steam CDN images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
