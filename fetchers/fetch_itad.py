#!/usr/bin/env python3
"""Fetch current prices from IsThereAnyDeal for every connected wishlist.

By default we only look up wishlist titles - those are the ones where a price
drop matters. Pass ``--include-library`` to also look up every owned game.

Each priced row records ``match``: ``"appid"`` when ITAD resolved it from a
Steam app id (exact) or ``"title"`` for a fuzzy title lookup. Deal alerts only
fire on ``appid`` matches.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from clients.itad_client import ItadClient, ItadError
from fetchers._base import (
    add_allow_empty_arg,
    configure_stdout,
    refuse_drift_result,
    refuse_empty_result,
)
from fetchers._progress import EXIT_CODE_AUTH, HeartbeatTimer, RunStats, started
from fetchers.registry import WISHLIST_JSON_BY_KEY
from shared.fx import ensure_fx_rates
from shared.money import country_to_currency
from shared.profile_paths import catalog_path, itad_path
from shared.safe_write import safe_write_text
from shared.wishlist_fx import refresh_wishlist_fx_after_itad
from shared.wishlist_keys import steam_appid_for, wishlist_lookup_key

ITAD_JSON = Path("itad_prices.json")
LIBRARY_FILES = [
    "games_steam.json",
    "games_gog.json",
    "games_psn.json",
    "games_epic.json",
    "games_amazon.json",
    "games_nintendo.json",
]
# Uncached ITAD title lookups per run (1.5s each). Cached lookups are free and
# never count, so a large first-time wishlist resolves across a few runs
# instead of stalling the queue.
ITAD_LOOKUP_BUDGET = 200


def _load_games(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    games = data.get("games") if isinstance(data, dict) else None
    return [g for g in games if isinstance(g, dict)] if isinstance(games, list) else []


def _collect_titles(
    include_library: bool,
    *,
    library_stores: set[str] | None = None,
    include_wishlist: bool = True,
) -> list[tuple[str, str, int | None]]:
    """(lookup_key, title, steam_appid) for every title to price."""
    seen: set[str] = set()
    out: list[tuple[str, str, int | None]] = []

    def add(key: str | None, title: str, appid: int | None) -> None:
        title = (title or "").strip()
        if not key or not title or key in seen:
            return
        seen.add(key)
        out.append((key, title, appid))

    if include_wishlist:
        for fetcher_key, filename in WISHLIST_JSON_BY_KEY.items():
            wp = catalog_path(filename)
            if not wp.exists():
                continue
            for g in _load_games(wp):
                add(
                    wishlist_lookup_key(fetcher_key, g),
                    g.get("name") or "",
                    steam_appid_for(fetcher_key, g),
                )

    if include_library:
        for path in LIBRARY_FILES:
            store_key = path.replace("games_", "").replace(".json", "")
            if library_stores and store_key not in library_stores:
                continue
            p = catalog_path(path)
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            store = data.get("store") or store_key
            for g in data.get("games", []):
                gid = g.get("id") or g.get("appid")
                if gid is None:
                    continue
                appid = None
                if store == "steam":
                    appid = steam_appid_for("wishlistSteam", {"appid": gid})
                elif g.get("steam_appid") is not None:
                    appid = steam_appid_for("", g)
                add(f"{store}:{gid}", g.get("name") or "", appid)

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
    parser.add_argument(
        "--stores",
        nargs="+",
        metavar="STORE",
        help="With --include-library, only price these library stores (e.g. nintendo).",
    )
    parser.add_argument(
        "--skip-wishlist",
        action="store_true",
        help="Skip wishlist titles (library-only ITAD run).",
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

    titles = _collect_titles(
        include_library=args.include_library,
        library_stores=set(args.stores) if args.stores else None,
        include_wishlist=not args.skip_wishlist,
    )
    if args.limit:
        titles = titles[: args.limit]
    scope_parts: list[str] = []
    if not args.skip_wishlist:
        scope_parts.append("wishlist")
    if args.include_library:
        if args.stores:
            scope_parts.append(f"library ({', '.join(sorted(args.stores))})")
        else:
            scope_parts.append("library")
    scope = " + ".join(scope_parts) or "titles"

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

    print(f"Looking up ITAD prices for {len(titles)} {scope} titles...", flush=True)

    try:
        client = ItadClient(api_key, country=args.country)
    except ItadError as e:
        stats.error(str(e))
        mark_invalid("itad", error=str(e))
        return stats.finish("fetch_itad", t0, exit_code=EXIT_CODE_AUTH)

    plain_by_key: dict[str, str] = {}
    match_by_key: dict[str, str] = {}
    is_cached = getattr(client, "is_lookup_cached", None)
    uncached_used = 0
    deferred = 0
    lookup_hb = HeartbeatTimer(interval=25.0)
    try:
        for i, (key, title, appid) in enumerate(titles, 1):
            lookup_hb.tick_progress(i, len(titles), "ITAD lookup", title[:40])
            if i % 10 == 0 or i == 1:
                print(f"[{i}/{len(titles)}] {title[:50]}", flush=True)
                lookup_hb.reset()
            if is_cached is not None and not is_cached(title, appid=appid):
                if uncached_used >= ITAD_LOOKUP_BUDGET:
                    deferred += 1
                    continue
                uncached_used += 1
            game_id = client.lookup_title(title, appid=appid)
            if game_id:
                plain_by_key[key] = game_id
                match_by_key[key] = "appid" if appid else "title"
            else:
                stats.warn(f"no ITAD match for {title!r}")

        if deferred:
            print(
                f"Deferred {deferred} new title lookup(s) to the next run "
                f"(limit {ITAD_LOOKUP_BUDGET} new lookups per run).",
                flush=True,
            )
        print(f"Resolved {len(plain_by_key)}/{len(titles)} ITAD ids. Fetching prices...", flush=True)
        # Titles is non-empty here (the empty-input case returns early above), so a
        # zero resolution means every wishlist title failed to match - refuse the
        # empty overwrite rather than wipe existing prices.
        empty_exit = refuse_empty_result(
            len(plain_by_key),
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
            by_key[key] = {**prices_by_plain[plain], "match": match_by_key.get(key, "title")}
        else:
            stats.warn(f"no price data for {key}")

    out = itad_path()
    empty_priced = refuse_empty_result(
        len(by_key),
        label="ITAD priced rows",
        allow_empty=args.allow_empty,
        output_path=out,
    )
    if empty_priced is not None:
        return stats.finish("fetch_itad", t0, exit_code=empty_priced)
    drift = refuse_drift_result(
        len(by_key),
        label="ITAD priced rows",
        allow_drift=args.allow_drift,
        output_path=out,
    )
    if drift is not None:
        return stats.finish("fetch_itad", t0, exit_code=drift)

    merged_by_key: dict[str, dict] = {}
    if out.exists():
        try:
            prior = json.loads(out.read_text(encoding="utf-8"))
            prior_map = prior.get("by_key")
            if isinstance(prior_map, dict):
                merged_by_key.update(prior_map)
        except (OSError, json.JSONDecodeError):
            pass
    merged_by_key.update(by_key)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "country": args.country,
        "currency": country_to_currency(args.country),
        "count": len(merged_by_key),
        "by_key": merged_by_key,
    }
    safe_write_text(out, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {len(by_key)} new price row(s); {len(merged_by_key)} total in {ITAD_JSON}.", flush=True)
    fx_files, fx_rows = refresh_wishlist_fx_after_itad(args.country)
    if fx_rows:
        print(
            f"FX: converted {fx_rows} wishlist row(s) across {fx_files} catalog(s) "
            f"to {country_to_currency(args.country)}.",
            flush=True,
        )
    stats.ok = len(by_key)
    return stats.finish(
        "fetch_itad",
        t0,
        exit_code=0,
        extra=f"{len(by_key)}/{len(titles)} priced",
    )


if __name__ == "__main__":
    raise SystemExit(main())
