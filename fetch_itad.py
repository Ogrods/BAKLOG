#!/usr/bin/env python3
"""Fetch current prices from IsThereAnyDeal for the wishlist.

By default we only look up wishlist titles - those are the ones where a price
drop matters. Pass ``--include-library`` to also look up every owned game.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from auth import resolve_env
from fetchers._base import add_allow_empty_arg, refuse_empty_result
from fetchers._progress import RunStats, started
from itad_client import ItadClient, ItadError
from shared.money import country_to_currency
from shared.profile_paths import catalog_path, itad_path
from shared.safe_write import safe_write_text

ITAD_JSON = Path("itad_prices.json")
LIBRARY_FILES = [
    "games_steam.json",
    "games_gog.json",
    "games_psn.json",
    "games_epic.json",
    "games_amazon.json",
]
WISHLIST_FILE = "games_wishlist.json"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _collect_titles(include_library: bool) -> list[tuple[str, str]]:
    """(lookup_key, title) - lookup_key is store:id or wishlist:appid."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(key: str, title: str) -> None:
        if not title or key in seen:
            return
        seen.add(key)
        out.append((key, title.strip()))

    wp = catalog_path(WISHLIST_FILE)
    if wp.exists():
        data = json.loads(wp.read_text(encoding="utf-8"))
        for g in data.get("games", []):
            appid = g.get("appid") or g.get("id")
            add(f"wishlist:{appid}", g.get("name") or "")

    if include_library:
        for path in LIBRARY_FILES:
            p = Path(path)
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            store = data.get("store") or path.replace("games_", "").replace(".json", "")
            for g in data.get("games", []):
                gid = g.get("id") or g.get("appid")
                if gid is None:
                    continue
                add(f"{store}:{gid}", g.get("name") or "")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch ITAD prices into itad_prices.json")
    default_country = os.environ.get("ITAD_COUNTRY", "US").strip().upper() or "US"
    parser.add_argument(
        "--country",
        default=default_country,
        help="ITAD country code (default ITAD_COUNTRY env or US)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max titles (0 = all)")
    parser.add_argument(
        "--include-library",
        action="store_true",
        help="Also look up every owned game (slow; default is wishlist only).",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_itad")
    stats = RunStats()
    load_dotenv()
    api_key = resolve_env("ITAD_API_KEY", provider="itad")
    if not api_key:
        stats.error("Set ITAD_API_KEY in .env (free key from https://isthereanydeal.com/dev/api/)")
        return stats.finish("fetch_itad", t0, exit_code=1)

    titles = _collect_titles(include_library=args.include_library)
    if args.limit:
        titles = titles[: args.limit]
    scope = "library + wishlist" if args.include_library else "wishlist"
    print(f"Looking up ITAD prices for {len(titles)} {scope} titles...")

    try:
        client = ItadClient(api_key, country=args.country)
    except ItadError as e:
        stats.error(str(e))
        return stats.finish("fetch_itad", t0, exit_code=1)

    plain_by_key: dict[str, str] = {}
    for i, (key, title) in enumerate(titles, 1):
        if i % 10 == 0 or i == 1:
            print(f"[{i}/{len(titles)}] {title[:50]}", flush=True)
        appid = None
        if key.startswith("steam:") or key.startswith("wishlist:"):
            try:
                appid = int(key.split(":", 1)[1])
            except ValueError:
                appid = None
        game_id = client.lookup_title(title, appid=appid)
        if game_id:
            plain_by_key[key] = game_id
        else:
            stats.warn(f"no ITAD match for {title!r}")

    print(f"Resolved {len(plain_by_key)}/{len(titles)} ITAD ids. Fetching prices...", flush=True)
    if titles and not plain_by_key and not args.allow_empty:
        stats.error(
            f"Resolved 0/{len(titles)} ITAD ids — refusing to overwrite {ITAD_JSON}."
        )
        stats.error("If this is expected, re-run with --allow-empty.")
        return stats.finish("fetch_itad", t0, exit_code=2)

    plains = list(set(plain_by_key.values()))
    prices_by_plain = client.prices_for_plains(plains)

    by_key: dict[str, dict] = {}
    for key, plain in plain_by_key.items():
        if plain in prices_by_plain:
            by_key[key] = prices_by_plain[plain]
        else:
            stats.warn(f"no price data for {key}")

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "country": args.country,
        "currency": country_to_currency(args.country),
        "count": len(by_key),
        "by_key": by_key,
    }
    out = itad_path()
    safe_write_text(out, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {len(by_key)} price rows to {ITAD_JSON}.", flush=True)
    stats.ok = len(by_key)
    exit_code = 0 if by_key or args.allow_empty else 2
    return stats.finish(
        "fetch_itad",
        t0,
        exit_code=exit_code,
        extra=f"{len(by_key)}/{len(titles)} priced",
    )


if __name__ == "__main__":
    raise SystemExit(main())
