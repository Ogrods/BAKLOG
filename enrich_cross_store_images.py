#!/usr/bin/env python3
"""Backfill header/library images for non-Steam rows via Steam store search."""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import requests
from dotenv import load_dotenv

from fetchers._base import catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, started
from itch_game import itch_is_videogame as _itch_is_videogame
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

STORE_FILES: list[tuple[Path, str, Callable[[dict], bool] | None]] = [
    (Path("games_gog.json"), "gog", None),
    (Path("games_psn.json"), "psn", None),
    (Path("games_epic.json"), "epic", None),
    (Path("games_amazon.json"), "amazon", None),
    (Path("games_xbox.json"), "xbox", None),
    (Path("games_battlenet.json"), "battlenet", None),
    (Path("games_ubisoft.json"), "ubisoft", None),
    (Path("games_nintendo.json"), "nintendo", None),
    (Path("games_humble.json"), "humble", None),
    (Path("games_itch.json"), "itch", _itch_is_videogame),
    (Path("games_ea.json"), "ea", None),
    (Path("games_wishlist.json"), "wishlist", None),
    (Path("games_wishlist_gog.json"), "wishlist", None),
    (Path("games_wishlist_epic.json"), "wishlist", None),
    (Path("games_wishlist_psn.json"), "wishlist", None),
    (Path("games_wishlist_ubisoft.json"), "wishlist", None),
    (Path("games_wishlist_xbox.json"), "wishlist", None),
    (Path("games_wishlist_nintendo.json"), "wishlist", None),
    (Path("games_wishlist_humble.json"), "wishlist", None),
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


def is_steamstatic_url(url: str) -> bool:
    return "steamstatic.com" in (url or "")


def needs_lowres_upgrade(g: dict) -> bool:
    if g.get("image_source") in ("steam_search", "steam_search_upgrade"):
        return False
    lib = g.get("library_image") or ""
    hdr = g.get("header_image") or ""
    if not lib and not hdr:
        return False
    if lib.endswith(".eprt") or hdr.endswith(".eprt"):
        return False
    if is_steamstatic_url(lib) or is_steamstatic_url(hdr):
        return False
    return True


def should_process(g: dict, *, upgrade_lowres: bool) -> bool:
    if needs_images(g):
        return True
    if upgrade_lowres and needs_lowres_upgrade(g):
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
    parser.add_argument(
        "--upgrade-lowres",
        action="store_true",
        help="Re-source native-store art (non-steamstatic URLs) to sharper Steam CDN images.",
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
    lowres_checked: set[str] = set(meta.get("lowres_checked", []))
    if args.retry_misses:
        print(f"--retry-misses: clearing {len(no_steam_match)} cached non-matches", flush=True)
        no_steam_match.clear()
        print(f"--retry-misses: clearing {len(lowres_checked)} cached low-res checks", flush=True)
        lowres_checked.clear()
    cache_lock = Lock()

    def process(g: dict, store: str) -> dict | None:
        missing = needs_images(g)
        upgrading = args.upgrade_lowres and needs_lowres_upgrade(g)
        if not missing and not upgrading:
            return None
        key = f"{store}:{g.get('id')}"
        with cache_lock:
            if key in no_steam_match:
                return None
            if upgrading and key in lowres_checked:
                return None
        appid = g.get("steam_appid")
        if not appid:
            appid = steam_search_appid(g.get("name", ""))
        if not appid:
            with cache_lock:
                no_steam_match.add(key)
                if upgrading:
                    lowres_checked.add(key)
            return None
        header, library = image_urls(appid)
        g = dict(g)
        g["header_image"] = header
        g["library_image"] = library
        g["steam_appid"] = appid
        g["image_source"] = "steam_search_upgrade" if upgrading and not missing else "steam_search"
        with cache_lock:
            if upgrading:
                lowres_checked.add(key)
        return g

    for rel, store, row_filter in STORE_FILES:
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        eligible = [g for g in games if row_filter is None or row_filter(g)]
        todo = [g for g in eligible if should_process(g, upgrade_lowres=args.upgrade_lowres)]
        if not todo:
            print(f"{path.name}: nothing to enrich", flush=True)
            continue
        skip_cached = sum(
            1 for g in todo
            if f"{store}:{g.get('id')}" in no_steam_match
            or (
                args.upgrade_lowres
                and needs_lowres_upgrade(g)
                and f"{store}:{g.get('id')}" in lowres_checked
            )
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
        completed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process, g, store): g["id"] for g in todo}
            for fut in as_completed(futures):
                gid = futures[fut]
                completed += 1
                if completed % 25 == 0:
                    hb.tick(f"{path.name}: {completed}/{len(todo)} covers — still working")
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
                "fetched_at": datetime.now(UTC).isoformat(),
                "last_updated": updated,
                "no_steam_match": sorted(no_steam_match),
                "lowres_checked": sorted(lowres_checked),
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
