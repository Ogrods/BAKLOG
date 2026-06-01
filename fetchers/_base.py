"""Common helpers for per-store fetch scripts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.json_util import dumps_games_json
from shared.safe_write import safe_write_text


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


def add_allow_empty_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow writing an empty result (e.g. genuinely empty wishlist).",
    )


def refuse_empty_result(
    items: list[Any] | int,
    *,
    label: str,
    allow_empty: bool,
    output_path: Path | None = None,
) -> int | None:
    """Return exit code 2 when result is empty and --allow-empty was not passed."""
    count = len(items) if isinstance(items, list) else items
    if count or allow_empty:
        return None
    where = f" ({output_path})" if output_path else ""
    print(
        f"ERROR: {label} returned 0 items{where} — refusing to overwrite existing file.\n"
        "If this is genuinely empty, re-run with --allow-empty.",
        file=sys.stderr,
        flush=True,
    )
    return 2


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
    """Write games_*.json atomically with a rotated backup.

    Routes through ``shared.safe_write.safe_write_text``: the previous on-disk
    file is copied to ``data/games_backups/<stem>/`` (keeping the last 10
    successful runs), then the new content is written via temp file +
    os.replace so a kill-mid-write cannot leave a truncated file.
    """
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": store,
        "game_count": len(games),
        "games": games,
    }
    if dry_run:
        return False
    safe_write_text(path, dumps_games_json(payload))
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
