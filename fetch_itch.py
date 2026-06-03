#!/usr/bin/env python3
"""Fetch itch.io owned games and write games_itch.json.

Requires ``ITCH_API_KEY`` in .env (https://itch.io/user/settings/api-keys).

Notes
-----
- Includes free games and claimed bundle items.
- Unclaimed bundle items (e.g. Palestine/Racial Justice bundles) won't appear
  until you claim each one on itch.io.
- itch doesn't expose playtime or aggregate ratings, so those fields stay
  empty. HLTB is best-effort (most jam games won't have entries).
- All owned keys are written to JSON (including tools, soundtracks, etc.).
  The dashboard itch.io tab hides non-games by default; use the filter toggle
  to show everything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from fetchers._base import (
    add_allow_empty_arg,
    add_dry_run_arg,
    add_hltb_args,
    carry_enrichment,
    configure_stdout,
    load_existing_games,
    merge_cached_row,
    print_id_diff,
    refuse_empty_result,
    write_games_json,
    catalog_file,
    write_catalog_text,
)
from itch_game import itch_is_videogame
from auth import mark_invalid, resolve_env
from auth.manager import is_local_provider_disabled
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from itch_client import ItchApiError, ItchAuthError, ItchClient

GAMES_ITCH_JSON = Path("games_itch.json")
HLTB_DELAY_SEC = 1.0
LEGACY_ROW_SOURCE = "api"

# Fields refreshed from itch.io on every fetch; everything else is preserved from cache.
FETCHER_AUTHORITATIVE = frozenset({
    "store", "id", "itch_id", "name", "header_image", "library_image",
    "release_date", "genres", "store_url", "type", "price", "price_initial",
    "discount_percent", "currency", "publisher", "short_text",
    "classification", "min_price", "in_press_system",
    "download_key_id", "purchase_id", "source",
    "playtime_minutes", "last_played",
})


def _release_date(game: dict) -> str | None:
    for key in ("published_at", "created_at"):
        raw = game.get(key)
        if isinstance(raw, str) and raw:
            return raw[:10]
    return None


_ITCH_NOISE_GENRES = {
    "default", "html", "html5", "flash", "java", "unity", "godot",
    "physical_game", "physical game", "assets", "asset_pack", "asset pack",
    "tool", "book", "comic", "soundtrack", "other", "game",
}


def _genres(game: dict) -> list[str]:
    """Collect itch.io tags as genres, filtering out classification/engine noise.

    The itch.io owned-keys API does not expose real genres in the listing
    endpoint - the ``classification`` field already captures format (game vs.
    tool vs. soundtrack, etc.) and ``type`` is engine metadata (html, flash).
    Neither belongs in the genres array. Tags array (if present) holds real
    genre-ish tags such as "shooter" or "platformer".
    """

    genres: list[str] = []
    for key in ("tags", "tag_list"):
        val = game.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    genres.append(item.strip())
        elif isinstance(val, str) and val.strip():
            genres.append(val.strip())
    cleaned = []
    seen = set()
    for g in genres:
        norm = g.strip().lower()
        if not norm or norm in _ITCH_NOISE_GENRES:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(g)
    return cleaned


def _build_row(entry: dict, hltb: dict | None) -> dict | None:
    game = entry.get("game") or {}
    gid = game.get("id")
    if gid is None:
        return None
    user = game.get("user") or {}
    cover = game.get("cover_url") or game.get("still_cover_url")
    row = {
        "store": "itch",
        "id": int(gid),
        "itch_id": int(gid),
        "name": (game.get("title") or "Untitled").strip(),
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": cover,
        "library_image": cover,
        "release_date": _release_date(game),
        "genres": _genres(game),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": game.get("url"),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "publisher": user.get("username") or user.get("display_name"),
        "short_text": game.get("short_text"),
        "classification": game.get("classification"),
        "min_price": game.get("min_price"),
        "in_press_system": bool(game.get("in_press_system")),
        "download_key_id": entry.get("id"),
        "purchase_id": entry.get("purchase_id"),
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


def _effective_row_source(row: dict) -> str:
    s = row.get("source")
    if s in ("local", "api"):
        return str(s)
    return LEGACY_ROW_SOURCE


def _match_key(row: dict) -> str:
    gid = row.get("itch_id") or row.get("id")
    if gid is not None:
        return f"itch_id:{gid}"
    return f"id:{row.get('id')}"


def _source_priority(source: str) -> int:
    return 2 if source == "local" else 1


def _pick_winner(row_a: dict, row_b: dict, current_source: str) -> dict:
    sa = _effective_row_source(row_a)
    sb = _effective_row_source(row_b)
    pa, pb = _source_priority(sa), _source_priority(sb)
    if pa > pb:
        return carry_enrichment(row_a, row_b)
    if pb > pa:
        return carry_enrichment(row_b, row_a)
    if sa == current_source:
        return carry_enrichment(row_a, row_b)
    return carry_enrichment(row_b, row_a)


def merge_itch_sources(
    current_rows: list[dict],
    carried_rows: list[dict],
    current_source: str,
) -> list[dict]:
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for row in carried_rows + current_rows:
        key = _match_key(row)
        if key in by_key:
            by_key[key] = _pick_winner(by_key[key], row, current_source)
        else:
            by_key[key] = row
            order.append(key)
    return [by_key[k] for k in order]


def _count_rows_for_source(games: list[dict], source: str) -> int:
    return sum(1 for g in games if _effective_row_source(g) == source)


def refuse_itch_source_drift(
    new_same_source_count: int,
    *,
    source: str,
    allow_drift: bool,
    output_path: Path,
    threshold: float = 0.5,
) -> int | None:
    if allow_drift:
        return None
    path = catalog_file(output_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    games = data.get("games")
    if not isinstance(games, list):
        return None
    prev = _count_rows_for_source(games, source)
    if prev <= 0:
        return None
    floor = max(1, int(prev * threshold))
    if new_same_source_count >= floor:
        return None
    pct = (new_same_source_count / prev * 100) if prev else 0.0
    print(
        f"ERROR: itch.io {source} slice drift refused — new={new_same_source_count}, "
        f"previous={prev}, floor={floor} (≥{int(threshold * 100)}% of prior), "
        f"ratio≈{pct:.0f}%.\n"
        "Reason: same-source row count fell below the drift guard. Re-run with "
        "--allow-drift if the drop is expected.",
        file=sys.stderr,
        flush=True,
    )
    return 3


def _butler_db_ready(db_path: Path | None) -> bool:
    if is_local_provider_disabled("itch_local"):
        return False
    from itch_local_client import default_butler_db

    path = db_path if db_path is not None else default_butler_db()
    return path.is_file()


def _api_creds_ready() -> bool:
    return bool(resolve_env("ITCH_API_KEY", provider="itch"))


def resolve_source(requested: str, db_path: Path | None) -> str:
    src = (requested or "auto").strip().lower()
    if src not in ("auto", "api", "local"):
        raise ValueError(f"unknown --source {requested!r}")
    if src != "auto":
        return src
    if _butler_db_ready(db_path):
        return "local"
    if _api_creds_ready():
        return "api"
    raise RuntimeError(
        "itch app database not found and no ITCH_API_KEY saved.\n"
        "Install/sign in to the itch desktop app, or paste an API key on the Connections page."
    )


def _build_row_from_local(rec: dict, hltb: dict | None, source: str) -> dict:
    gid = int(rec["itch_id"])
    row = {
        "store": "itch",
        "id": gid,
        "itch_id": gid,
        "name": rec["name"],
        "source": source,
        "playtime_minutes": rec.get("playtime_minutes") or 0,
        "last_played": rec.get("last_played"),
        "header_image": rec.get("header_image"),
        "library_image": rec.get("library_image"),
        "release_date": rec.get("release_date"),
        "genres": _genres({"tags": [], "classification": rec.get("classification")}),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": rec.get("store_url"),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "publisher": None,
        "short_text": rec.get("short_text"),
        "classification": rec.get("classification"),
        "min_price": rec.get("min_price"),
        "in_press_system": rec.get("in_press_system"),
        "download_key_id": rec.get("download_key_id"),
        "purchase_id": None,
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


def _tag_api_row(row: dict) -> dict:
    row = dict(row)
    row["source"] = "api"
    return row


def _load_local_records(db_path: Path | None) -> list[dict]:
    from itch_local_client import ItchLocalClient

    client = ItchLocalClient(db_path)
    print(f"Reading itch.io library from:\n  {client.db_path}", flush=True)
    return client.get_library_records()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch itch.io library (local app DB or API key)"
    )
    parser.add_argument(
        "--source",
        choices=("auto", "api", "local"),
        default=os.getenv("ITCH_SOURCE", "auto").strip().lower() or "auto",
        help="auto: butler.db when present, else API key (default: auto)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override itch butler.db path (local source only)",
    )
    add_hltb_args(parser)
    parser.add_argument(
        "--min-price",
        type=int,
        default=None,
        help="Skip games whose listed min_price is below this (in cents). Useful to drop free jam games.",
    )
    add_dry_run_arg(parser)
    add_allow_empty_arg(parser)
    parser.add_argument(
        "--games-only",
        action="store_true",
        help="Only write rows classified as videogames (tools/soundtracks/etc. omitted).",
    )
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_itch")
    stats = RunStats()
    load_dotenv()

    db_path = args.db_path
    if db_path is None:
        env_db = os.getenv("ITCH_BUTLER_DB", "").strip()
        db_path = Path(env_db) if env_db else None

    try:
        source = resolve_source(args.source, db_path)
    except (RuntimeError, ValueError) as e:
        stats.error(str(e))
        return stats.finish("fetch_itch", t0, exit_code=1)

    print(f"itch.io source: {source}", flush=True)

    hltb_client = HltbClient()
    existing = load_existing_games(GAMES_ITCH_JSON)
    carried_rows = [
        row
        for row in existing.values()
        if _effective_row_source(row) != source
    ]
    if carried_rows:
        print(
            f"Keeping {len(carried_rows)} row(s) from the other itch.io source.",
            flush=True,
        )

    current_rows: list[dict] = []

    if source == "local":
        try:
            from itch_local_client import ItchLocalError

            records = _load_local_records(db_path)
        except ItchLocalError as e:
            stats.error(str(e))
            return stats.finish("fetch_itch", t0, exit_code=1)

        empty_exit = refuse_empty_result(
            records,
            label="itch.io local library",
            allow_empty=args.allow_empty,
            output_path=GAMES_ITCH_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_itch", t0, exit_code=empty_exit)

        filtered = records
        if args.min_price is not None:
            before = len(filtered)
            filtered = [
                r for r in filtered if (r.get("min_price") or 0) >= args.min_price
            ]
            skipped = before - len(filtered)
            if skipped:
                print(f"  filtered {skipped} items below --min-price", flush=True)

        print(f"Found {len(filtered)} owned titles in butler.db.", flush=True)

        for i, rec in enumerate(filtered, 1):
            gid = rec["itch_id"]
            name = rec["name"]
            print(f"[{i}/{len(filtered)}] {name}", flush=True)

            cached = existing.get(str(gid))
            if cached is not None and _effective_row_source(cached) != source:
                cached = None

            hltb = None
            hltb_updated = False
            if not args.skip_hltb and not (
                args.only_new and cached and cached.get("hltb_main_hours") is not None
            ):
                try:
                    time.sleep(HLTB_DELAY_SEC)
                    hltb = hltb_client.lookup(name)
                    hltb_updated = bool(hltb)
                except Exception as e:
                    print(f"  HLTB warning: {e}", flush=True)
            elif cached and not args.skip_hltb:
                hltb = {
                    "hltb_main_hours": cached.get("hltb_main_hours"),
                    "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                    "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                    "hltb_match_confidence": cached.get("hltb_match_confidence"),
                    "hltb_name": cached.get("hltb_name"),
                }

            current_rows.append(
                merge_cached_row(
                    _build_row_from_local(rec, hltb, source),
                    cached,
                    authoritative=FETCHER_AUTHORITATIVE,
                    hltb_updated=hltb_updated,
                )
            )
    else:
        api_key = resolve_env("ITCH_API_KEY", provider="itch")
        if not api_key:
            stats.error(
                "Set ITCH_API_KEY on the Connections page "
                "(https://itch.io/user/settings/api-keys)"
            )
            return stats.finish("fetch_itch", t0, exit_code=1)

        try:
            client = ItchClient(api_key)
            user = client.me()
            if user.get("username"):
                print(f"Signed in to itch.io as {user['username']}", flush=True)
            print("Walking owned-keys pages (this can take a minute)...", flush=True)
            keys = client.all_owned_keys()
        except ItchAuthError as e:
            mark_invalid("itch", error=str(e))
            stats.error(str(e))
            return stats.finish("fetch_itch", t0, exit_code=EXIT_CODE_AUTH)
        except ItchApiError as e:
            stats.error(f"itch.io API error: {e}")
            return stats.finish("fetch_itch", t0, exit_code=1)

        empty_exit = refuse_empty_result(
            keys,
            label="itch.io API library",
            allow_empty=args.allow_empty,
            output_path=GAMES_ITCH_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_itch", t0, exit_code=empty_exit)

        print(f"Found {len(keys)} owned keys.", flush=True)

        filtered_entries: list[dict] = []
        skipped_price = 0
        for entry in keys:
            game = entry.get("game") or {}
            if args.min_price is not None and (game.get("min_price") or 0) < args.min_price:
                skipped_price += 1
                continue
            filtered_entries.append(entry)
        if skipped_price:
            print(f"  filtered {skipped_price} items below --min-price", flush=True)

        for i, entry in enumerate(filtered_entries, 1):
            game = entry.get("game") or {}
            name = (game.get("title") or "Untitled").strip()
            gid = game.get("id")
            if gid is None:
                continue
            print(f"[{i}/{len(filtered_entries)}] {name}", flush=True)

            cached = existing.get(str(gid))
            if cached is not None and _effective_row_source(cached) != source:
                cached = None

            hltb = None
            hltb_updated = False
            if not args.skip_hltb and not (
                args.only_new and cached and cached.get("hltb_main_hours") is not None
            ):
                try:
                    time.sleep(HLTB_DELAY_SEC)
                    hltb = hltb_client.lookup(name)
                    hltb_updated = bool(hltb)
                except Exception as e:
                    print(f"  HLTB warning: {e}", flush=True)
            elif cached and not args.skip_hltb:
                hltb = {
                    "hltb_main_hours": cached.get("hltb_main_hours"),
                    "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                    "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                    "hltb_match_confidence": cached.get("hltb_match_confidence"),
                    "hltb_name": cached.get("hltb_name"),
                }

            row = _build_row(entry, hltb)
            if row:
                current_rows.append(
                    merge_cached_row(
                        _tag_api_row(row),
                        cached,
                        authoritative=FETCHER_AUTHORITATIVE,
                        hltb_updated=hltb_updated,
                    )
                )

    games_out = merge_itch_sources(current_rows, carried_rows, source)

    if args.games_only:
        before = len(games_out)
        games_out = [g for g in games_out if itch_is_videogame(g)]
        skipped = before - len(games_out)
        if skipped:
            print(f"  --games-only: omitted {skipped} non-game row(s).", flush=True)

    existing_ids = set(existing.keys())
    new_ids = {str(g["id"]) for g in games_out}
    print_id_diff(existing_ids, new_ids)
    preserved_enrichment = sum(
        1
        for g in games_out
        if existing.get(str(g["id"]))
        and (
            g.get("steam_review_percent") is not None
            or g.get("hltb_main_hours") is not None
        )
    )
    if preserved_enrichment:
        print(
            f"  {preserved_enrichment} rows kept enrichment from cache (reviews/HLTB)",
            flush=True,
        )

    if args.dry_run:
        print("\nDry run — not writing games_itch.json.", flush=True)
        return stats.finish("fetch_itch", t0, exit_code=0, extra="dry run")

    drift_exit = refuse_itch_source_drift(
        len(current_rows),
        source=source,
        allow_drift=args.allow_drift,
        output_path=GAMES_ITCH_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_itch", t0, exit_code=drift_exit)

    sorted_games = sorted(games_out, key=lambda g: g["name"].lower())
    write_games_json(GAMES_ITCH_JSON, store="itch", games=sorted_games)
    print(f"\nWrote {len(sorted_games)} games to {GAMES_ITCH_JSON}.", flush=True)
    print("Reload the dashboard to see your itch.io library.", flush=True)
    stats.ok = len(sorted_games)
    return stats.finish("fetch_itch", t0, exit_code=0, extra=f"{len(sorted_games)} games")


if __name__ == "__main__":
    raise SystemExit(main())
