#!/usr/bin/env python3
"""Backfill header/library images for non-Steam rows via Steam store search."""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import requests
from dotenv import load_dotenv

from fetchers._base import catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, started
from shared.profile_paths import cache_json_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}
SEARCH_DELAY = 0.4
WORKERS = 4
HEARTBEAT_EVERY = 25


def meta_file() -> Path:
    return cache_json_path("cross_store_images_meta.json")

STORE_FILES = [
    (Path("games_gog.json"), "gog"),
    (Path("games_psn.json"), "psn"),
    (Path("games_epic.json"), "epic"),
    (Path("games_amazon.json"), "amazon"),
    (Path("games_xbox.json"), "xbox"),
    (Path("games_battlenet.json"), "battlenet"),
    (Path("games_ubisoft.json"), "ubisoft"),
    (Path("games_nintendo.json"), "nintendo"),
    (Path("games_humble.json"), "humble"),
    (Path("games_ea.json"), "ea"),
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
            snippet = (r.text or "")[:120].replace("\n", " ")
            print(
                f"  HTTP {r.status_code} for {r.url}: {snippet}",
                flush=True,
            )
            return None
        items = r.json().get("items") or []
    except Exception as exc:
        print(f"  search failed for {name!r}: {exc}", flush=True)
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


def load_meta() -> dict:
    path = meta_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help="Re-search Steam for rows previously cached as having no Steam match.",
    )
    args = parser.parse_args()

    t0 = started("enrich_cross_store_images")
    stats = RunStats()
    updated = 0
    hb = HeartbeatTimer(25.0)
    meta = load_meta()
    # Persistent "this row exists on (store, id) but has no Steam match" set
    # so a re-click doesn't waste a Steam search hit on Hearthstone again.
    no_steam_match: set[str] = set(meta.get("no_steam_match", []))
    if args.retry_misses:
        print(f"--retry-misses: clearing {len(no_steam_match)} cached non-matches", flush=True)
        no_steam_match.clear()
    cache_lock = Lock()

    def process(g: dict, store: str) -> dict | None:
        if not needs_images(g):
            return None
        key = f"{store}:{g.get('id')}"
        with cache_lock:
            if key in no_steam_match:
                return None
        appid = g.get("steam_appid")
        if not appid:
            appid = steam_search_appid(g.get("name", ""))
        if not appid:
            with cache_lock:
                no_steam_match.add(key)
            return None
        header, library = image_urls(appid)
        g = dict(g)
        g["header_image"] = header
        g["library_image"] = library
        g["steam_appid"] = appid
        g["image_source"] = "steam_search"
        return g

    for rel, store in STORE_FILES:
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        todo = [g for g in games if needs_images(g)]
        if not todo:
            print(f"{path.name}: nothing to enrich", flush=True)
            continue
        skip_cached = sum(
            1 for g in todo if f"{store}:{g.get('id')}" in no_steam_match
        )
        fresh = len(todo) - skip_cached
        if fresh == 0:
            print(
                f"{path.name}: {len(todo)} need cover but all are cached as "
                f"\"no Steam match\" — skipping (use --retry-misses to retry).",
                flush=True,
            )
            continue
        print(
            f"{path.name}: enriching {fresh} games"
            f" ({skip_cached} skipped from cached non-matches)...",
            flush=True,
        )
        by_id = {g["id"]: g for g in games}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process, g, store): g["id"] for g in todo}
            for fut in as_completed(futures):
                gid = futures[fut]
                completed += 1
                try:
                    new_g = fut.result()
                except Exception as e:
                    stats.warn(f"{gid}: {e}")
                    continue
                if new_g:
                    by_id[gid] = new_g
                    updated += 1
                    stats.ok += 1
                    print(f"  + {new_g.get('name', gid)}", flush=True)
        data["games"] = list(by_id.values())
        write_catalog_text(rel, json.dumps(data, indent=2, ensure_ascii=False))

    meta = meta_file()
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": updated,
                "no_steam_match": sorted(no_steam_match),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"\nUpdated {updated} games with Steam CDN images. "
        f"{len(no_steam_match)} rows cached as \"no Steam match\".",
        flush=True,
    )
    return stats.finish(
        "enrich_cross_store_images",
        t0,
        exit_code=0,
        extra=f"{updated} images",
    )


if __name__ == "__main__":
    raise SystemExit(main())
