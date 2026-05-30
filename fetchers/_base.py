"""Common helpers for per-store fetch scripts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.json_util import dumps_games_json


def configure_stdout() -> None:
    """Avoid UnicodeEncodeError on Windows consoles (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def add_hltb_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="Only HLTB-lookup games not already in the output file",
    )


def add_dry_run_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary and skip writing the output JSON file",
    )


def load_existing_games(path: Path, *, id_key: str = "id") -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    games = data.get("games") or []
    return {str(g[id_key]): g for g in games if isinstance(g, dict) and g.get(id_key) is not None}


def write_games_json(
    path: Path,
    *,
    store: str,
    games: list[dict[str, Any]],
    dry_run: bool = False,
) -> bool:
    """Write games_*.json; return True if written."""
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": store,
        "game_count": len(games),
        "games": games,
    }
    if dry_run:
        return False
    path.write_text(dumps_games_json(payload), encoding="utf-8")
    return True


def print_id_diff(
    existing_ids: set[str],
    new_ids: set[str],
    *,
    label: str = "Summary",
) -> tuple[set[str], set[str]]:
    added = new_ids - existing_ids
    removed = existing_ids - new_ids
    print(f"\n{label}: {len(new_ids)} rows ({len(added)} new, {len(removed)} dropped from file)")
    if added:
        print(f"  New ids: {len(added)}")
    if removed:
        print(f"  Removed ids: {len(removed)}")
    return added, removed


def merge_cached_row(
    fresh: dict[str, Any],
    cached: dict[str, Any] | None,
    *,
    authoritative: frozenset[str],
    hltb_updated: bool = False,
    hltb_keys: tuple[str, ...] = (
        "hltb_main_hours",
        "hltb_main_extra_hours",
        "hltb_completionist_hours",
        "hltb_match_confidence",
        "hltb_name",
    ),
) -> dict[str, Any]:
    """Overlay fetcher-authoritative fields onto cached row, preserving enrichment."""
    if not cached:
        return fresh
    merged = dict(cached)
    for key in authoritative:
        if key in fresh:
            merged[key] = fresh[key]
    if hltb_updated:
        for key in hltb_keys:
            merged[key] = fresh.get(key)
    return merged


RowBuilder = Callable[..., dict[str, Any]]

HLTB_ROW_KEYS = (
    "hltb_main_hours",
    "hltb_main_extra_hours",
    "hltb_completionist_hours",
    "hltb_match_confidence",
    "hltb_name",
)


def hltb_dict_from_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    if row.get("hltb_main_hours") is None and not row.get("hltb_name"):
        return None
    return {key: row.get(key) for key in HLTB_ROW_KEYS}


def resolve_hltb_for_row(
    *,
    skip_hltb: bool,
    only_new: bool,
    cached: dict[str, Any] | None,
    name: str,
    client: Any,
    delay_sec: float,
) -> tuple[dict[str, Any] | None, bool]:
    """Return (hltb_fields_dict, hltb_updated). Preserves cached HLTB when skipping lookups."""
    import time

    if skip_hltb:
        return hltb_dict_from_row(cached), False
    if only_new and cached and cached.get("hltb_main_hours") is not None:
        return hltb_dict_from_row(cached), False
    if cached and cached.get("hltb_main_hours") is not None and not only_new:
        return hltb_dict_from_row(cached), False
    try:
        time.sleep(delay_sec)
        result = client.lookup(name)
        return result, bool(result)
    except Exception as e:
        print(f"  HLTB warning: {e}")
        return hltb_dict_from_row(cached), False
