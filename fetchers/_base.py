"""Common helpers for per-store fetch scripts."""

from __future__ import annotations

STEAM_CREDENTIALS_HINT = (
    "Steam is not connected for this profile. "
    "Open Connections → Steam → Connect (sign in to capture your API key and SteamID)."
)

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.json_util import dumps_games_json
from shared.profile_paths import resolve_catalog_path
from shared.safe_write import safe_write_text


def catalog_file(path: Path) -> Path:
    """Resolved on-disk path for a catalog JSON under the active profile."""
    return resolve_catalog_path(path)


def write_catalog_text(path: Path, text: str) -> Path:
    """Atomic write + rotated backup for a games_*.json / itad catalog file."""
    disk = resolve_catalog_path(path)
    safe_write_text(disk, text)
    return disk


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
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help=(
            "Allow writing a result that is sharply smaller than the previous "
            "fetch (default threshold: 50%%). Use when a store legitimately "
            "lost titles (delisted, deauthorized devices, etc.)."
        ),
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


def _previous_game_count(output_path: Path | None) -> int | None:
    """Read game_count from the previous on-disk file, if any. Resilient to
    malformed JSON or schema drift — callers should treat None as 'no baseline'."""
    if output_path is not None:
        output_path = resolve_catalog_path(output_path)
    if output_path is None or not output_path.exists():
        return None
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    gc = data.get("game_count")
    if isinstance(gc, int) and gc >= 0:
        return gc
    games = data.get("games")
    if isinstance(games, list):
        return len(games)
    return None


def refuse_drift_result(
    items: list[Any] | int,
    *,
    label: str,
    allow_drift: bool,
    output_path: Path | None,
    threshold: float = 0.5,
) -> int | None:
    """Return exit code 3 when the new result is sharply smaller than the
    previous on-disk file.

    Pairs with ``refuse_empty_result`` so a fetcher whose API silently returns
    3 rows instead of the usual 600 fails loudly instead of overwriting good
    data. ``threshold`` is the fraction of the previous count the new count
    must clear (default 0.5 — i.e. anything <50% of the last successful run is
    refused). ``--allow-drift`` opts out (delisted accounts, region swaps,
    etc.).

    First-run behavior: when no previous file exists or it has no count
    field, this function returns None (no baseline → can't measure drift).
    """
    new_count = len(items) if isinstance(items, list) else items
    prev = _previous_game_count(output_path)
    if prev is None or prev <= 0 or allow_drift:
        return None
    # Strict-less so a result that exactly matches the floor is allowed.
    floor = max(1, int(prev * threshold))
    if new_count >= floor:
        return None
    pct = (new_count / prev * 100) if prev else 0.0
    where = f" ({output_path})" if output_path else ""
    print(
        f"ERROR: {label} returned {new_count} items{where}, but the previous run "
        f"had {prev} (≈{pct:.0f}% — under the {int(threshold * 100)}% floor).\n"
        "Likely a broken auth or upstream API. If this drop is real, re-run with --allow-drift.",
        file=sys.stderr,
        flush=True,
    )
    return 3


def load_existing_games(path: Path, *, id_key: str = "id") -> dict[str, dict[str, Any]]:
    path = resolve_catalog_path(path)
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
    path = resolve_catalog_path(path)
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


# Image fields owned by a store fetcher only when the fetcher actually has a URL.
# When the fresh row's value is falsy we keep whatever's cached — typically the
# Steam-CDN URL written by enrich_cross_store_images.py — instead of clobbering
# enrichment back to None on every fetcher rerun.
_IMAGE_KEYS = frozenset({"header_image", "library_image"})

# Fields written by enrich scripts (reviews, HLTB, co-op tags), not store fetchers.
ENRICHMENT_FIELDS = (
    "steam_review_percent",
    "steam_review_count",
    "steam_review_desc",
    "hltb_main_hours",
    "hltb_main_extra_hours",
    "hltb_completionist_hours",
    "hltb_match_confidence",
    "hltb_name",
    "coop_online",
    "coop_local",
)

# When a fetcher reruns with empty/zero fresh values, keep populated cache values.
_PRESERVE_IF_FRESH_EMPTY = frozenset(
    {
        "playtime_minutes",
        "last_played",
        *ENRICHMENT_FIELDS,
    }
)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def carry_enrichment(winner: dict, loser: dict | None) -> dict:
    """Copy enricher-written fields from the displaced row when the winner lacks them."""
    if not loser:
        return winner
    out = dict(winner)
    for key in ENRICHMENT_FIELDS:
        win_val = out.get(key)
        lose_val = loser.get(key)
        if (win_val is None or win_val == "" or win_val is False) and lose_val not in (
            None,
            "",
            False,
        ):
            out[key] = lose_val
    return out


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
        if key not in fresh:
            continue
        if key in _IMAGE_KEYS and not fresh[key]:
            continue
        if (
            key in _PRESERVE_IF_FRESH_EMPTY
            and _is_empty(fresh[key])
            and not _is_empty(merged.get(key))
        ):
            continue
        merged[key] = fresh[key]
    if hltb_updated:
        for key in hltb_keys:
            fresh_val = fresh.get(key)
            if _is_empty(fresh_val) and not _is_empty(merged.get(key)):
                continue
            merged[key] = fresh_val
    return merged


RowBuilder = Callable[..., dict[str, Any]]
