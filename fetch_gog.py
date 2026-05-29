#!/usr/bin/env python3
"""Fetch GOG library data and write games_gog.json for the dashboard."""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import os
from dotenv import load_dotenv

from gog_client import GogAuthError, GogClient
from hltb_client import HltbClient

GAMES_GOG_JSON = Path("games_gog.json")
HLTB_DELAY_SEC = 1.0


def _configure_stdout() -> None:
    """Avoid UnicodeEncodeError on Windows consoles (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _gog_image_urls(raw: str | None) -> tuple[str | None, str | None]:
    """Turn GOG's bare image hash into usable (header, library_cover) URLs.

    GOG's CDN serves the hash without a file extension; the bare path 404s.
    Append `.jpg` for the original (landscape banner) and `_glx_vertical_cover.jpg`
    for the portrait cover used by Galaxy. The HTML img onerror handler falls
    back to the header if the vertical cover doesn't exist for older titles.
    """
    if not raw:
        return None, None
    url = raw
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return None, None
    if url.endswith(".jpg") or url.endswith(".png"):
        return url, url
    return f"{url}.jpg", f"{url}_glx_vertical_cover.jpg"


def _normalize_gog_store_url(product: dict, gog_id: int) -> str:
    """GOG API often returns a site-relative path; the dashboard needs an absolute URL."""
    url = (product.get("url") or "").strip()
    slug = product.get("slug") or str(gog_id)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.gog.com{url}"
    if url:
        return f"https://www.gog.com/{url.lstrip('/')}"
    return f"https://www.gog.com/en/game/{slug}"


def _extract_genres(product: dict, details: dict | None) -> list[str]:
    genres: list[str] = []
    for source in (details or {}, product):
        for key in ("genres", "tags"):
            raw = source.get(key)
            if not raw:
                continue
            for g in raw:
                if isinstance(g, str):
                    genres.append(g)
                elif isinstance(g, dict):
                    label = g.get("name") or g.get("title") or g.get("slug")
                    if label:
                        genres.append(str(label))
    return list(dict.fromkeys(genres))


def _playtime_minutes(details: dict | None) -> int:
    if not details:
        return 0
    for key in ("playTime", "playtime", "timePlayed"):
        val = details.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            return int(val // 60) if val > 500 else int(val)
        if isinstance(val, dict):
            mins = val.get("minutes") or val.get("total") or 0
            return int(mins)
    return 0


def _build_game_row(
    product: dict,
    details: dict | None,
    hltb: dict | None,
) -> dict | None:
    gog_id = int(product.get("id") or product.get("productId") or 0)
    if not gog_id:
        return None

    media_type = product.get("mediaType") or product.get("media_type")
    if media_type not in (None, 1, "1", "game"):
        return None

    name = (
        product.get("title")
        or product.get("name")
        or (details or {}).get("title")
        or f"GOG {gog_id}"
    )
    image = (
        product.get("image")
        or product.get("img")
        or (details or {}).get("backgroundImage")
        or (details or {}).get("image")
    )
    header_url, library_url = _gog_image_urls(image)

    release = product.get("releaseDate") or product.get("release_date")
    if isinstance(release, dict):
        release = release.get("date") or release.get("title")

    price_block = product.get("price") or {}
    if isinstance(price_block, dict):
        final_price = price_block.get("finalAmount") or price_block.get("final")
        currency = price_block.get("currency") or product.get("currency")
        discount = price_block.get("discount") or price_block.get("discountPercent")
        price_str = None
        if final_price is not None and currency:
            price_str = f"{final_price} {currency}"
    else:
        price_str = None
        currency = None
        discount = None

    row = {
        "store": "gog",
        "id": gog_id,
        "gog_id": gog_id,
        "name": name,
        "playtime_minutes": _playtime_minutes(details),
        "last_played": None,
        "header_image": header_url,
        "library_image": library_url,
        "release_date": release,
        "genres": _extract_genres(product, details),
        "tags": [],
        "metacritic_score": product.get("criticsScore") or product.get("metacriticScore"),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _normalize_gog_store_url(product, gog_id),
        "type": "game",
        "price": price_str,
        "price_initial": None,
        "discount_percent": discount,
        "currency": currency,
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


def load_existing() -> dict[int, dict]:
    if not GAMES_GOG_JSON.exists():
        return {}
    data = json.loads(GAMES_GOG_JSON.read_text(encoding="utf-8"))
    return {g["id"]: g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch GOG library into games_gog.json")
    parser.add_argument("--refresh", action="store_true", help="Ignore API cache")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_gog.json")
    parser.add_argument("--id", type=int, dest="gog_id", help="Fetch a single product by GOG ID")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    args = parser.parse_args()
    _configure_stdout()

    load_dotenv()
    gog_al = os.getenv("GOG_AL", "").strip()
    if not gog_al:
        print("Set GOG_AL in .env (see README for cookie instructions).", file=sys.stderr)
        return 1

    try:
        gog = GogClient(gog_al)
        gog.validate_session()
    except GogAuthError as e:
        print(str(e), file=sys.stderr)
        return 1

    hltb_client = HltbClient()
    existing = load_existing()

    print("Fetching owned games from GOG...")
    try:
        products = gog.get_all_filtered_products(refresh=args.refresh)
    except GogAuthError as e:
        print(str(e), file=sys.stderr)
        return 1

    if not products:
        owned_ids = gog.get_owned_game_ids()
        print(f"Found {len(owned_ids)} owned IDs (building from details)...")
        products = [{"id": pid, "title": f"GOG {pid}"} for pid in owned_ids]
    else:
        print(f"Found {len(products)} products in library.")

    if args.gog_id:
        products = [p for p in products if int(p.get("id") or p.get("productId") or 0) == args.gog_id]
        if not products:
            products = [{"id": args.gog_id, "title": f"GOG {args.gog_id}"}]

    games_out: list[dict] = []
    skipped = 0

    for i, product in enumerate(products, 1):
        gog_id = int(product.get("id") or product.get("productId") or 0)
        name = product.get("title") or product.get("name") or str(gog_id)

        if args.only_new and gog_id in existing and not args.refresh and not args.gog_id:
            games_out.append(existing[gog_id])
            continue

        print(f"[{i}/{len(products)}] {name} ({gog_id})")

        cached_row = existing.get(gog_id)
        need_details = args.refresh or cached_row is None or args.gog_id

        details = None
        if need_details:
            try:
                details = gog.get_product_details(gog_id, refresh=args.refresh)
            except Exception as e:
                print(f"  Details warning: {e}")

        hltb = None
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

        row = _build_game_row(product, details, hltb)
        if row is None:
            skipped += 1
            continue
        games_out.append(row)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "gog",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    GAMES_GOG_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(games_out)} games to {GAMES_GOG_JSON} (skipped {skipped} non-game items).")
    print("Open index.html in your browser to view the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
