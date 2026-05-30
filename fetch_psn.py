#!/usr/bin/env python3
"""Fetch PlayStation library data and write games_psn.json for the dashboard."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from hltb_client import HltbClient
from psn_client import PsnAuthError, PsnClient, PsnGameEntry

GAMES_PSN_JSON = Path("games_psn.json")
HLTB_DELAY_SEC = 1.0

# Manual denylist of PSN ids (CUSA / NPWR / concept) for entries Sony reports
# as "library" titles but are really streaming apps / utilities. Add an id here
# whenever the fetcher picks up junk you don't want to see again.
DENYLIST_IDS: set[str] = {
    "CUSA20387_00",  # PeacockTV
    "PPSA06399_00",  # PAC-MAN WORLD Re-PAC Chrome Noir Chogokin skin (cosmetic DLC)
    "CUSA03390_00",  # NFL app
    "CUSA06566_00",  # NBA app
    "CUSA02012_00",  # Media Player
}


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
    if entry.play_count is not None:
        tags.append(f"Sessions {entry.play_count}")

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
        "header_image": entry.image_url,
        "library_image": entry.image_url,
        "release_date": None,
        "genres": [],
        "psn_platforms": list(entry.platforms or []),
        "tags": tags,
        "trophy_progress": entry.trophy_progress,
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
    if not GAMES_PSN_JSON.exists():
        return {}
    data = json.loads(GAMES_PSN_JSON.read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PSN library into games_psn.json")
    parser.add_argument("--refresh", action="store_true", help="Refetch library metadata from PSN")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_psn.json")
    parser.add_argument("--id", dest="psn_id", help="Fetch a single title by np_communication_id or title_id")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    args = parser.parse_args()
    _configure_stdout()

    load_dotenv()
    npsso = os.getenv("PSN_NPSSO", "").strip()
    if not npsso:
        print("Set PSN_NPSSO in .env (see README for NPSSO instructions).", file=sys.stderr)
        return 1

    try:
        psn = PsnClient(npsso)
        online_id = psn.validate_session()
    except PsnAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    hltb_client = HltbClient()
    existing = load_existing()

    print(f"Fetching PSN library for {online_id}...")
    try:
        library = psn.collect_library()
    except PsnAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.psn_id:
        library = [entry for entry in library if entry.id == args.psn_id]
        if not library:
            print(f"No PSN title found with id {args.psn_id!r}.", file=sys.stderr)
            return 1

    denied = sum(1 for e in library if e.id in DENYLIST_IDS)
    library = [e for e in library if e.id not in DENYLIST_IDS]

    dropped = getattr(psn, "last_dedupe_dropped", 0)
    filtered = getattr(psn, "last_filtered_non_games", 0)
    parts: list[str] = []
    if dropped:
        parts.append(f"merged {dropped} cross-platform duplicates")
    if filtered:
        parts.append(f"filtered {filtered} non-games")
    if denied:
        parts.append(f"denylisted {denied}")
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
        if not args.skip_hltb and (
            args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(entry.name)
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

        games_out.append(_build_game_row(entry, hltb))

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "psn",
        "online_id": online_id,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    GAMES_PSN_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(games_out)} games to {GAMES_PSN_JSON}.")
    print("Open index.html in your browser to view the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
