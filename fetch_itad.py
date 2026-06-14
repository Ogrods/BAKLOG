#!/usr/bin/env python3
"""Fetch current prices from IsThereAnyDeal for the wishlist.

By default we only look up wishlist titles - those are the ones where a price
drop matters. Pass ``--include-library`` to also look up every owned game.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from fetchers._base import add_allow_empty_arg, configure_stdout, refuse_empty_result
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from itad_client import ItadClient, ItadError
from shared.fx import ensure_fx_rates
from shared.money import country_to_currency
from shared.profile_paths import catalog_path, itad_path
from shared.safe_write import safe_write_text
from shared.wishlist_fx import refresh_wishlist_fx_after_itad

ITAD_JSON = Path("itad_prices.json")
LIBRARY_FILES = [
    "games_steam.json",
    "games_gog.json",
    "games_psn.json",
    "games_epic.json",
    "games_amazon.json",
]
WISHLIST_FILE = "games_wishlist.json"


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
            p = catalog_path(path)
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
    configure_stdout()
    t0 = started("fetch_itad")
    stats = RunStats()
    load_dotenv()
    try:
        ensure_fx_rates(warn_stale=True)
    except RuntimeError as e:
        stats.warn(f"FX rates unavailable: {e} (wishlist FX conversion skipped)")
    api_key = resolve_env("ITAD_API_KEY", provider="itad")
    if not api_key:
        stats.error("Set ITAD_API_KEY in .env (free key from https://isthereanydeal.com/dev/api/)")
        return stats.finish("fetch_itad", t0, exit_code=1)

    titles = _collect_titles(include_library=args.include_library)
    if args.limit:
        titles = titles[: args.limit]
    scope = "library + wishlist" if args.include_library else "wishlist"

    # Empty input is "nothing to do", not a failure. Previously an empty wishlist
    # fell through to a 0-row write and exit 2 with no explanation, surfacing as a
    # bare "failed" chip. Detect it up front and tell the user what to do instead,
    # leaving any existing itad_prices.json untouched.
    if not titles:
        if args.include_library:
            stats.warn(
                "No wishlist or library titles found to price yet. Add games to a "
                "store wishlist (or import a library), then run ITAD prices again."
            )
        else:
            stats.warn(
                "Your wishlist is empty, so there is nothing for ITAD to price. "
                "ITAD tracks price drops on wishlist titles - add games to a store "
                "wishlist and re-fetch it, then run ITAD prices again. To also track "
                "prices for games you own, run with --include-library."
            )
        print(f"No {scope} titles to look up - skipping ITAD price fetch.", flush=True)
        return stats.finish("fetch_itad", t0, exit_code=0, extra="0 titles to price")

    print(f"Looking up ITAD prices for {len(titles)} {scope} titles...")

    try:
        client = ItadClient(api_key, country=args.country)
    except ItadError as e:
        stats.error(str(e))
        mark_invalid("itad", error=str(e))
        return stats.finish("fetch_itad", t0, exit_code=EXIT_CODE_AUTH)

    plain_by_key: dict[str, str] = {}
    try:
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
        # Titles is non-empty here (the empty-input case returns early above), so a
        # zero resolution means every wishlist title failed to match - refuse the
        # empty overwrite rather than wipe existing prices.
        empty_exit = refuse_empty_result(
            plain_by_key,
            label="ITAD price resolution",
            allow_empty=args.allow_empty,
            output_path=ITAD_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_itad", t0, exit_code=empty_exit)

        plains = list(set(plain_by_key.values()))
        prices_by_plain = client.prices_for_plains(plains)
    except ItadError as e:
        stats.error(str(e))
        mark_invalid("itad", error=str(e))
        return stats.finish("fetch_itad", t0, exit_code=EXIT_CODE_AUTH)

    by_key: dict[str, dict] = {}
    for key, plain in plain_by_key.items():
        if plain in prices_by_plain:
            by_key[key] = prices_by_plain[plain]
        else:
            stats.warn(f"no price data for {key}")

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "country": args.country,
        "currency": country_to_currency(args.country),
        "count": len(by_key),
        "by_key": by_key,
    }
    out = itad_path()
    safe_write_text(out, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {len(by_key)} price rows to {ITAD_JSON}.", flush=True)
    fx_files, fx_rows = refresh_wishlist_fx_after_itad(args.country)
    if fx_rows:
        print(
            f"FX: converted {fx_rows} wishlist row(s) across {fx_files} catalog(s) "
            f"to {country_to_currency(args.country)}.",
            flush=True,
        )
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
