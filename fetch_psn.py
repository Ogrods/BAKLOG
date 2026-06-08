#!/usr/bin/env python3
"""Fetch PlayStation library data and write games_psn.json for the dashboard."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from fetchers._authoritative import PSN
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    apply_carry_forward,
    catalog_file,
    merge_cached_row,
    refuse_drift_result,
    refuse_empty_result,
    row_key_by_id,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from psn_client import PsnAuthError, PsnClient, PsnGameEntry

GAMES_PSN_JSON = Path("games_psn.json")
HLTB_DELAY_SEC = 1.0


def _configure_stdout() -> None:
    """Avoid UnicodeEncodeError on Windows consoles (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _build_game_row(entry: PsnGameEntry, hltb: dict | None) -> dict:
    tags: list[str] = []
    if entry.trophy_progress is not None:
        tags.append(f"Trophy {entry.trophy_progress}%")

    row = {
        "store": "psn",
        "id": entry.id,
        "psn_id": entry.id,
        "np_communication_id": entry.np_communication_id,
        "title_id": entry.title_id,
        "concept_id": entry.concept_id,
        "name": entry.name,
        "playtime_minutes": entry.playtime_minutes,
        "last_played": entry.last_played,
        "first_played": entry.first_played,
        "play_count": entry.play_count,
        "header_image": entry.image_url,
        "library_image": entry.image_url,
        "release_date": None,
        "genres": [],
        "psn_platforms": list(entry.platforms or []),
        "tags": tags,
        "trophy_progress": entry.trophy_progress,
        "psn_trophies_earned": entry.trophies_earned,
        "psn_trophies_total": entry.trophies_total,
        "psn_has_platinum": entry.has_platinum,
        "psn_platinum_earned": entry.platinum_earned,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": entry.store_url or "https://www.playstation.com/",
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
    if not catalog_file(GAMES_PSN_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_PSN_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PSN library into games_psn.json")
    parser.add_argument("--refresh", action="store_true", help="Refetch library metadata from PSN")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_psn.json")
    parser.add_argument("--id", dest="psn_id", help="Fetch a single title by np_communication_id or title_id")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_psn")
    stats = RunStats()

    load_dotenv()
    npsso = resolve_env("PSN_NPSSO", provider="psn")
    if not npsso:
        stats.error("Set PSN_NPSSO in .env (see README for NPSSO instructions).")
        return stats.finish("fetch_psn", t0, exit_code=1)

    try:
        psn = PsnClient(npsso)
        online_id = psn.validate_session()
    except PsnAuthError as exc:
        mark_invalid("psn", error=str(exc))
        stats.error(str(exc))
        return stats.finish("fetch_psn", t0, exit_code=EXIT_CODE_AUTH)

    hltb_client = HltbClient()
    existing = load_existing()

    print(f"Fetching PSN library for {online_id}...")
    try:
        library = psn.collect_library()
    except PsnAuthError as exc:
        mark_invalid("psn", error=str(exc))
        stats.error(str(exc))
        return stats.finish("fetch_psn", t0, exit_code=EXIT_CODE_AUTH)

    if args.psn_id:
        library = [entry for entry in library if entry.id == args.psn_id]
        if not library:
            stats.error(f"No PSN title found with id {args.psn_id!r}.")
            return stats.finish("fetch_psn", t0, exit_code=1)
    else:
        empty_exit = refuse_empty_result(
            library,
            label="PSN library API",
            allow_empty=args.allow_empty,
            output_path=GAMES_PSN_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_psn", t0, exit_code=empty_exit)

    dropped = getattr(psn, "last_dedupe_dropped", 0)
    filtered = getattr(psn, "last_filtered_non_games", 0)
    parts: list[str] = []
    if dropped:
        parts.append(f"merged {dropped} cross-platform duplicates")
    if filtered:
        parts.append(f"filtered {filtered} non-games")
    suffix = f" ({', '.join(parts)})" if parts else ""
    print(f"Found {len(library)} titles{suffix}.")

    games_out: list[dict] = []

    for i, entry in enumerate(library, 1):
        if args.only_new and entry.id in existing and not args.refresh and not args.psn_id:
            games_out.append(existing[entry.id])
            continue

        print(f"[{i}/{len(library)}] {entry.name} ({entry.id})")

        cached_row = existing.get(entry.id)

        hltb = None
        hltb_updated = False
        if not args.skip_hltb and (
            args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(entry.name)
                hltb_updated = bool(hltb)
            except Exception as exc:
                print(f"  HLTB warning: {exc}")
        elif cached_row:
            hltb = {
                "hltb_main_hours": cached_row.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached_row.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached_row.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached_row.get("hltb_match_confidence"),
                "hltb_name": cached_row.get("hltb_name"),
            }

        games_out.append(
            merge_cached_row(
                _build_game_row(entry, hltb),
                cached_row,
                authoritative=PSN,
                hltb_updated=hltb_updated,
            )
        )

    empty_exit = refuse_empty_result(
        games_out,
        label="PSN library rows",
        allow_empty=args.allow_empty,
        output_path=GAMES_PSN_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_psn", t0, exit_code=empty_exit)
    if not args.psn_id:
        drift_exit = refuse_drift_result(
            games_out,
            label="PSN library rows",
            allow_drift=args.allow_drift,
            output_path=GAMES_PSN_JSON,
        )
        if drift_exit is not None:
            return stats.finish("fetch_psn", t0, exit_code=drift_exit)

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=row_key_by_id,
        no_carry=args.no_carry,
    )

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "psn",
        "online_id": online_id,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    write_catalog_text(GAMES_PSN_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_PSN_JSON}.", flush=True)
    print("Open index.html in your browser to view the dashboard.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_psn", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
