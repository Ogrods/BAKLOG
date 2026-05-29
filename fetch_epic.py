#!/usr/bin/env python3
"""Fetch Epic Games Store library into games_epic.json for the dashboard."""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from epic_client import EpicAuthError, EpicClient, LOGIN_URL
from hltb_client import HltbClient

GAMES_EPIC_JSON = Path("games_epic.json")
HLTB_DELAY_SEC = 1.0
CATALOG_WORKERS = 16

LIBRARY_IMAGE_TYPES = (
    "DieselGameBoxTall",
    "Thumbnail",
    "OfferImageTall",
    "VaultClosed",
    "DieselGameBox",
)
HEADER_IMAGE_TYPES = (
    "OfferImageWide",
    "DieselStoreFrontWide",
    "DieselGameBox",
    "Featured",
)


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _pick_image(key_images: list, types: tuple[str, ...]) -> str | None:
    by_type = {k.get("type"): k.get("url") for k in key_images if isinstance(k, dict)}
    for t in types:
        url = by_type.get(t)
        if url:
            return url
    return None


def _extract_genres(item: dict) -> list[str]:
    genres: list[str] = []
    for tag in item.get("tags") or []:
        if isinstance(tag, str):
            genres.append(tag)
        elif isinstance(tag, dict):
            name = tag.get("name") or tag.get("id")
            if name:
                genres.append(str(name))
    return list(dict.fromkeys(genres))


_PUBLIC_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_public_epic_slug(value: str | None) -> bool:
    """Real Epic store slugs are lowercase + digits + hyphens (e.g. ``fortnite``).

    Internal entitlement slugs like ``Fortnite_Studio`` or ``KingletAztec`` are
    PascalCase/snake_case and 404 on the public store.
    """
    return bool(value and _PUBLIC_SLUG.match(str(value).strip()))


def _epic_public_slug(item: dict, catalog_id: str) -> str | None:
    for key in ("productSlug", "urlSlug", "pageSlug"):
        slug = item.get(key)
        if _is_public_epic_slug(slug):
            return str(slug).strip()
    return None


def _epic_store_url(item: dict, catalog_id: str, name: str) -> str:
    slug = _epic_public_slug(item, catalog_id)
    if slug:
        return f"https://store.epicgames.com/en-US/p/{slug}"
    return f"https://store.epicgames.com/en-US/browse?q={quote(name)}"


def _epic_store_url_from_record(rec: dict, name: str) -> str:
    slug = rec.get("appName")
    if _is_public_epic_slug(slug):
        return f"https://store.epicgames.com/en-US/p/{slug}"
    return f"https://store.epicgames.com/en-US/browse?q={quote(name)}"


def _is_game_item(item: dict) -> bool:
    paths = [
        c.get("path", "")
        for c in (item.get("categories") or [])
        if isinstance(c, dict)
    ]
    if any("addons" in p and "games" not in p for p in paths):
        return False
    if any("games" in p for p in paths):
        return True
    if item.get("keyImages"):
        return True
    return bool(item.get("title"))


def _build_game_row(
    catalog_id: str,
    namespace: str,
    item: dict,
    hltb: dict | None,
) -> dict | None:
    if not _is_game_item(item):
        return None
    name = item.get("title") or catalog_id
    key_images = item.get("keyImages") or []
    header = _pick_image(key_images, HEADER_IMAGE_TYPES)
    library = _pick_image(key_images, LIBRARY_IMAGE_TYPES) or header
    store_url = _epic_store_url(item, catalog_id, name)

    release = None
    for info in item.get("releaseInfo") or []:
        if isinstance(info, dict) and info.get("date"):
            release = info["date"]
            break

    row = {
        "store": "epic",
        "id": f"{namespace}:{catalog_id}",
        "epic_namespace": namespace,
        "epic_catalog_id": catalog_id,
        "name": name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": header,
        "library_image": library,
        "release_date": release,
        "genres": _extract_genres(item),
        "tags": [],
        "metacritic_score": None,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": store_url,
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }
    if hltb:
        row.update(
            {
                "hltb_main_hours": hltb.get("hltb_main_hours"),
                "hltb_main_extra_hours": hltb.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": hltb.get("hltb_completionist_hours"),
                "hltb_match_confidence": hltb.get("hltb_match_confidence"),
                "hltb_name": hltb.get("hltb_name"),
            }
        )
    return row


def _build_game_row_from_record(
    rec: dict,
    catalog_item: dict | None,
    hltb: dict | None,
) -> dict | None:
    ns = rec.get("namespace")
    cid = rec.get("catalogItemId")
    if not ns or not cid:
        return None
    if catalog_item:
        row = _build_game_row(str(cid), str(ns), catalog_item, hltb)
        if row:
            return row
    name = rec.get("sandboxName") or rec.get("appName") or str(cid)
    row = {
        "store": "epic",
        "id": f"{ns}:{cid}",
        "epic_namespace": ns,
        "epic_catalog_id": cid,
        "name": name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": None,
        "library_image": None,
        "release_date": rec.get("acquisitionDate"),
        "genres": [],
        "tags": [],
        "metacritic_score": None,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _epic_store_url_from_record(rec, name),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }
    if hltb:
        row.update(
            {
                "hltb_main_hours": hltb.get("hltb_main_hours"),
                "hltb_main_extra_hours": hltb.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": hltb.get("hltb_completionist_hours"),
                "hltb_match_confidence": hltb.get("hltb_match_confidence"),
                "hltb_name": hltb.get("hltb_name"),
            }
        )
    return row


def load_existing() -> dict[str, dict]:
    if not GAMES_EPIC_JSON.exists():
        return {}
    data = json.loads(GAMES_EPIC_JSON.read_text(encoding="utf-8"))
    return {g["id"]: g for g in data.get("games", [])}


def print_auth_help() -> None:
    print(
        """
Epic login is NOT a cookie from DevTools.

1. Sign in at https://www.epicgames.com in your browser.
2. Open this URL in the same browser (copy/paste the whole line):

"""
        + LOGIN_URL
        + """

3. You should see a JSON page like:
   {"authorizationCode":"abc123...","redirectUrl":"..."}
4. Copy only the authorizationCode value into .env:
   EPIC_AUTH_CODE=abc123...
5. Run: python fetch_epic.py

The code expires in ~5 minutes. After the first successful run, a refresh
token is saved in cache/epic/session.json and you won't need the code again.
"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic library into games_epic.json")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch all catalog metadata")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    parser.add_argument("--auth-help", action="store_true", help="Print Epic login instructions")
    args = parser.parse_args()
    _configure_stdout()

    if args.auth_help:
        print_auth_help()
        return 0

    load_dotenv()
    auth_code = os.getenv("EPIC_AUTH_CODE", "").strip() or None

    try:
        client = EpicClient(auth_code=auth_code)
        print("Logging in to Epic...")
        client.login()
        print(f"  account {client.account_id}")
    except EpicAuthError as e:
        print(str(e), file=sys.stderr)
        print_auth_help()
        return 1

    print("Fetching library...")
    records = client.get_library_records()
    apps = [r for r in records if r.get("recordType") == "APPLICATION"]
    print(f"  {len(records)} entitlements, {len(apps)} applications")

    print(f"Fetching catalog metadata ({CATALOG_WORKERS} workers)...")
    catalog: dict[tuple[str, str], dict] = {}

    def fetch_one(rec: dict) -> tuple[tuple[str, str], dict | None]:
        ns, cid = str(rec["namespace"]), str(rec["catalogItemId"])
        return (ns, cid), client.get_catalog_item(ns, cid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=CATALOG_WORKERS) as ex:
        futures = [ex.submit(fetch_one, rec) for rec in apps]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            if i % 75 == 0 or i == len(futures):
                print(f"  catalog {i}/{len(futures)}")
            try:
                key, item = fut.result()
                if item:
                    catalog[key] = item
            except Exception as e:
                print(f"  catalog warning: {e}")

    print(f"  catalog hits: {len(catalog)}/{len(apps)}")

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []
    skipped = 0

    apps_sorted = sorted(
        apps,
        key=lambda r: (r.get("sandboxName") or r.get("appName") or "").lower(),
    )
    for i, rec in enumerate(apps_sorted, 1):
        ns, cid = str(rec["namespace"]), str(rec["catalogItemId"])
        row_id = f"{ns}:{cid}"
        item = catalog.get((ns, cid))
        name = (item or {}).get("title") or rec.get("sandboxName") or rec.get("appName") or cid

        if not args.refresh and row_id in existing and args.skip_hltb:
            games_out.append(existing[row_id])
            continue
        if (
            not args.refresh
            and row_id in existing
            and not args.skip_hltb
            and existing[row_id].get("hltb_main_hours") is not None
            and existing[row_id].get("library_image")
        ):
            games_out.append(existing[row_id])
            continue

        print(f"[{i}/{len(apps_sorted)}] {name}")

        hltb = None
        cached_row = existing.get(row_id)
        if not args.skip_hltb and (
            args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        elif cached_row:
            hltb = {
                "hltb_main_hours": cached_row.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached_row.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached_row.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached_row.get("hltb_match_confidence"),
                "hltb_name": cached_row.get("hltb_name"),
            }

        row = _build_game_row_from_record(rec, item, hltb)
        if row is None:
            skipped += 1
            continue
        games_out.append(row)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "epic",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    GAMES_EPIC_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(games_out)} games to {GAMES_EPIC_JSON} (skipped {skipped}).")
    print("Reload the dashboard (or click Reload library) to refresh Picks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
