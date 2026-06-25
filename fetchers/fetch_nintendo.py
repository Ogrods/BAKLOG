#!/usr/bin/env python3
"""Fetch Nintendo eShop purchase history into games_nintendo.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from auth.secrets import profile_dir
from clients.hltb_client import HltbClient
from clients.nintendo_client import (
    NintendoAuthError,
    NintendoCaptureError,
    NintendoClient,
    NintendoEndpointError,
)
from fetchers._authoritative import NINTENDO
from fetchers._base import (
    LAST_SEEN_FIELD,
    STALE_FIELD,
    STALE_SINCE_FIELD,
    add_allow_empty_arg,
    add_no_carry_arg,
    add_only_new_arg,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    refuse_empty_result,
    row_key_by_id,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from shared.profile_paths import personal_path
from shared.raw_dumps import profile_raw_dump_path

GAMES_NINTENDO_JSON = Path("games_nintendo.json")

NINTENDO_LEGACY_FIELD = "nintendo_legacy"
NINTENDO_DROPPED_KEY = "__nintendo_dropped_ids_v1"
NINTENDO_DRIFT_THRESHOLD = 0.5

NINTENDO_RAW_DUMP = profile_raw_dump_path("nintendo_raw.json")


def fetch_debug_json() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "nintendo" / "fetch_debug.json"


HLTB_DELAY_SEC = 1.0


def _norm_nintendo_title(name: str) -> str:
    return " ".join((name or "").lower().split())


# Skip non-game purchases (funds, subscriptions, vouchers).
SKIP_CONTENT_TYPES = frozenset(
    {
        "funds",
        "subscription",
        "subscription_pass",
        "voucher",
        "gift_card",
        "balance",
    }
)
SKIP_TITLE_PATTERNS = re.compile(
    r"\b(nintendo switch online|expansion pack|membership|e?shop\s+card|"
    r"add-on content bundle|funds)\b",
    re.I,
)


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").replace("®", "").replace("™", "").split()).strip()


def _is_game_transaction(tx: dict) -> bool:
    ctype = (tx.get("content_type") or "").lower()
    if ctype in SKIP_CONTENT_TYPES:
        return False
    title = tx.get("title") or ""
    if SKIP_TITLE_PATTERNS.search(title):
        return False
    # Refunds are negative entries for the same title.
    if (tx.get("transaction_type") or "").lower() == "refund":
        return False
    if not title.strip():
        return False
    return True


def _merge_transactions(transactions: list[dict]) -> list[dict]:
    """One row per title; keep earliest purchase date and tag DLC."""
    by_title: dict[str, dict] = {}
    for tx in transactions:
        if not _is_game_transaction(tx):
            continue
        name = _clean_name(str(tx.get("title") or ""))
        if not name:
            continue
        key = name.lower()
        ctype = (tx.get("content_type") or "").lower()
        is_dlc = ctype in ("dlc", "aoc", "addon", "add_on") or "dlc" in name.lower()
        date = tx.get("date") or ""
        tid = tx.get("transaction_id") or key

        if key not in by_title:
            by_title[key] = {
                "name": name,
                "id": str(tid),
                "nintendo_id": str(tid),
                "purchase_date": date,
                "device_type": tx.get("device_type"),
                "content_type": tx.get("content_type"),
                "tags": ["dlc"] if is_dlc else [],
            }
            continue
        row = by_title[key]
        if date and (not row.get("purchase_date") or date < row["purchase_date"]):
            row["purchase_date"] = date
        if is_dlc and "dlc" not in row["tags"]:
            row["tags"].append("dlc")

    return list(by_title.values())


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_NINTENDO_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_NINTENDO_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def load_existing_by_title(existing: dict[str, dict]) -> dict[str, dict]:
    """Title index for cache/carry when transaction ids churn between syncs."""
    by_title: dict[str, dict] = {}
    for row in existing.values():
        title_key = _norm_nintendo_title(str(row.get("name") or ""))
        if title_key and title_key not in by_title:
            by_title[title_key] = row
    return by_title


def load_nintendo_dropped_ids() -> set[str]:
    """Ids the user removed via bulk Remove; excluded from carry-forward."""
    path = personal_path()
    if not path.exists():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(doc, dict):
        return set()
    personal = doc.get("personal")
    if not isinstance(personal, dict):
        return set()
    raw = personal.get(NINTENDO_DROPPED_KEY)
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if item}


def _nintendo_drift_baseline(output_path: Path) -> int | None:
    """Fresh-slice count for drift guard (not total catalog including legacy rows)."""
    path = catalog_file(output_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    fresh_count = data.get("fresh_count")
    if isinstance(fresh_count, int) and fresh_count >= 0:
        return fresh_count
    games = data.get("games")
    if not isinstance(games, list):
        return None
    non_legacy = sum(
        1
        for row in games
        if isinstance(row, dict)
        and not row.get(NINTENDO_LEGACY_FIELD)
        and not row.get(STALE_FIELD)
    )
    if non_legacy > 0:
        return non_legacy
    game_count = data.get("game_count")
    if isinstance(game_count, int) and game_count >= 0:
        return game_count
    return len(games) or None


def refuse_nintendo_drift_result(
    items: list[dict],
    *,
    label: str,
    allow_drift: bool,
    output_path: Path,
) -> int | None:
    """Drift guard using fresh_count baseline so legacy carry rows do not block sync."""
    new_count = len(items)
    prev = _nintendo_drift_baseline(output_path)
    if prev is None or prev <= 0 or allow_drift:
        return None
    floor = max(1, int(prev * NINTENDO_DRIFT_THRESHOLD))
    if new_count >= floor:
        return None
    pct = (new_count / prev * 100) if prev else 0.0
    where = f" ({output_path})" if output_path else ""
    print(
        f"ERROR: {label} returned {new_count} items{where}, but the previous fresh "
        f"slice had {prev} (≈{pct:.0f}% — under the "
        f"{int(NINTENDO_DRIFT_THRESHOLD * 100)}% floor).\n"
        "Likely a broken auth or upstream API. If this drop is real, re-run with --allow-drift.",
        file=sys.stderr,
        flush=True,
    )
    return 3


def carry_forward_nintendo_legacy(
    fresh_rows: list[dict],
    existing_rows: list[dict],
    *,
    dropped_ids: set[str],
    key_fn,
    now_iso: str | None = None,
) -> list[dict]:
    """Union prior rows missing from the fresh fetch; tag nintendo_legacy, not stale."""
    now = now_iso or datetime.now(UTC).isoformat()
    present = {key_fn(row) for row in fresh_rows}
    present_titles = {
        _norm_nintendo_title(str(row.get("name") or ""))
        for row in fresh_rows
        if row.get("name")
    }
    out: list[dict] = []
    for row in fresh_rows:
        merged = dict(row)
        merged[LAST_SEEN_FIELD] = now
        merged.pop(STALE_FIELD, None)
        merged.pop(STALE_SINCE_FIELD, None)
        merged.pop(NINTENDO_LEGACY_FIELD, None)
        out.append(merged)
    carried = 0
    for old in existing_rows:
        key = key_fn(old)
        if key in present or key in dropped_ids:
            continue
        title_key = _norm_nintendo_title(str(old.get("name") or ""))
        if title_key and title_key in present_titles:
            continue
        legacy_row = dict(old)
        legacy_row[NINTENDO_LEGACY_FIELD] = True
        legacy_row.pop(STALE_FIELD, None)
        legacy_row.pop(STALE_SINCE_FIELD, None)
        legacy_row.setdefault(LAST_SEEN_FIELD, old.get(LAST_SEEN_FIELD))
        out.append(legacy_row)
        carried += 1
    if carried:
        print(
            f"  Carried forward {carried} legacy game(s) "
            f"({NINTENDO_LEGACY_FIELD}=true).",
            flush=True,
        )
    return out


def repair_nintendo_stale_catalog(
    games: list[dict],
    *,
    dropped_ids: set[str] | None = None,
) -> tuple[list[dict], int]:
    """One-shot: stale Nintendo rows from pre-legacy carry become nintendo_legacy."""
    dropped = dropped_ids or set()
    repaired = 0
    out: list[dict] = []
    for row in games:
        merged = dict(row)
        key = str(merged.get("id") or merged.get("nintendo_id") or "")
        if merged.get(STALE_FIELD) and key not in dropped:
            merged[NINTENDO_LEGACY_FIELD] = True
            merged.pop(STALE_FIELD, None)
            merged.pop(STALE_SINCE_FIELD, None)
            repaired += 1
        out.append(merged)
    return out, repaired


def maybe_repair_nintendo_catalog_on_disk(dropped_ids: set[str] | None = None) -> int:
    """Heal on-disk games_nintendo.json rows still flagged stale from older syncs."""
    path = catalog_file(GAMES_NINTENDO_JSON)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    games, repaired = repair_nintendo_stale_catalog(
        payload.get("games") or [],
        dropped_ids=dropped_ids,
    )
    if not repaired:
        return 0
    payload["games"] = games
    if not isinstance(payload.get("fresh_count"), int):
        payload["fresh_count"] = sum(
            1
            for row in games
            if isinstance(row, dict) and not row.get(NINTENDO_LEGACY_FIELD)
        )
    payload["game_count"] = len(games)
    write_catalog_text(
        GAMES_NINTENDO_JSON,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    print(
        f"  Repaired {repaired} stale Nintendo row(s) "
        f"({NINTENDO_LEGACY_FIELD}=true).",
        flush=True,
    )
    return repaired


def maybe_backfill_nintendo_catalog_meta() -> bool:
    """Heal envelopes written before fresh_count was introduced."""
    path = catalog_file(GAMES_NINTENDO_JSON)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    games = payload.get("games")
    if not isinstance(games, list):
        return False
    fresh_count = payload.get("fresh_count")
    game_count = payload.get("game_count")
    computed_fresh = sum(
        1
        for row in games
        if isinstance(row, dict) and not row.get(NINTENDO_LEGACY_FIELD)
    )
    computed_total = len(games)
    needs_write = False
    if not isinstance(fresh_count, int):
        payload["fresh_count"] = computed_fresh
        needs_write = True
    if not isinstance(game_count, int) or game_count != computed_total:
        payload["game_count"] = computed_total
        needs_write = True
    if not needs_write:
        return False
    write_catalog_text(
        GAMES_NINTENDO_JSON,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    print(
        f"  Backfilled Nintendo catalog meta "
        f"(fresh_count={payload['fresh_count']}, game_count={payload['game_count']}).",
        flush=True,
    )
    return True


def _build_row(item: dict, hltb: dict | None) -> dict:
    name = item["name"]
    nid = item["id"]
    row = {
        "store": "nintendo",
        "id": nid,
        "nintendo_id": nid,
        "name": name,
        "playtime_minutes": None,
        "last_played": None,
        "header_image": None,
        "library_image": None,
        "release_date": item.get("purchase_date"),
        "genres": [],
        "tags": list(item.get("tags") or []),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": f"https://www.nintendo.com/us/store/products/{quote(name)}/",
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "nintendo_platform": item.get("device_type"),
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


def _nintendo_connected() -> bool:
    prof = profile_dir("nintendo")
    if prof.exists() and any(prof.iterdir()):
        return True
    return bool(resolve_env("NINTENDO_COOKIE", provider="nintendo"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Nintendo eShop purchase history")
    parser.add_argument("--skip-hltb", action="store_true")
    add_only_new_arg(parser)
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=f"Write raw transactions to {NINTENDO_RAW_DUMP}",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Open the saved browser profile visibly (debug capture issues)",
    )
    parser.add_argument(
        "--dump-debug",
        action="store_true",
        help=f"Write capture diagnostics to {fetch_debug_json()}",
    )
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_nintendo")
    stats = RunStats()
    load_dotenv()

    if not _nintendo_connected():
        stats.error(
            "Nintendo is not connected. Open Connections → Nintendo → Connect and "
            "sign in at ec.nintendo.com/my/transactions/ (saved browser profile required)."
        )
        return stats.finish("fetch_nintendo", t0, exit_code=1)

    cookie = resolve_env("NINTENDO_COOKIE", provider="nintendo") or ""
    prof = profile_dir("nintendo")
    debug_path = fetch_debug_json() if args.dump_debug else None

    try:
        client = NintendoClient(
            cookie,
            profile_path=prof,
            headless=not args.headed,
            dump_debug_path=debug_path,
        )
        raw_tx = run_with_heartbeat(
            client.fetch_all_transactions,
            "Nintendo transactions",
        )
    except NintendoEndpointError as e:
        stats.error(str(e))
        return stats.finish("fetch_nintendo", t0, exit_code=1)
    except NintendoCaptureError as e:
        stats.error(str(e))
        return stats.finish("fetch_nintendo", t0, exit_code=1)
    except NintendoAuthError as e:
        mark_invalid("nintendo", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_nintendo", t0, exit_code=EXIT_CODE_AUTH)

    print(f"Fetched {len(raw_tx)} raw transactions.")

    if args.dump_raw:
        NINTENDO_RAW_DUMP.parent.mkdir(parents=True, exist_ok=True)
        NINTENDO_RAW_DUMP.write_text(
            json.dumps(raw_tx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote raw dump to {NINTENDO_RAW_DUMP}.")

    merged = _merge_transactions(raw_tx)
    print(f"Found {len(merged)} unique game/DLC titles (after filtering funds/NSO).")

    empty_exit = refuse_empty_result(
        merged,
        label="Nintendo library",
        allow_empty=args.allow_empty,
        output_path=GAMES_NINTENDO_JSON,
    )
    if empty_exit is not None:
        stats.error(
            f"No games found. Check {NINTENDO_RAW_DUMP} — session may be valid "
            "but account has no eShop purchases in the last ~2 years."
        )
        return stats.finish("fetch_nintendo", t0, exit_code=empty_exit)

    hltb_client = HltbClient()
    dropped_ids = load_nintendo_dropped_ids()
    maybe_repair_nintendo_catalog_on_disk(dropped_ids)
    maybe_backfill_nintendo_catalog_meta()
    existing = {
        key: row
        for key, row in load_existing().items()
        if key not in dropped_ids
    }
    existing_by_title = load_existing_by_title(existing)
    games_out: list[dict] = []
    for i, item in enumerate(merged, 1):
        cached = existing.get(str(item["id"]))
        if not cached:
            cached = existing_by_title.get(_norm_nintendo_title(item["name"]))
        if args.only_new and cached:
            games_out.append(cached)
            continue
        print(f"[{i}/{len(merged)}] {item['name']}")
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(item["name"])
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        games_out.append(
            merge_cached_row(
                _build_row(item, hltb),
                cached,
                authoritative=NINTENDO,
                hltb_updated=hltb_updated,
            )
        )

    drift_exit = refuse_nintendo_drift_result(
        games_out,
        label="Nintendo library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_NINTENDO_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_nintendo", t0, exit_code=drift_exit)

    fresh_count = len(games_out)
    if args.no_carry:
        final_games = [
            row for row in games_out if row_key_by_id(row) not in dropped_ids
        ]
    else:
        final_games = carry_forward_nintendo_legacy(
            games_out,
            list(existing.values()),
            dropped_ids=dropped_ids,
            key_fn=row_key_by_id,
        )
    if dropped_ids:
        final_games = [
            row for row in final_games if row_key_by_id(row) not in dropped_ids
        ]

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "nintendo",
        "fresh_count": fresh_count,
        "game_count": len(final_games),
        "note": (
            "eShop digital purchases only; ~2 year history limit; no cartridge games; "
            "older purchases kept as nintendo_legacy"
        ),
        "games": sorted(final_games, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_NINTENDO_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(final_games)} games to {GAMES_NINTENDO_JSON}.", flush=True)
    print("Reload the dashboard to see your Nintendo library.", flush=True)
    stats.ok = len(final_games)
    return stats.finish("fetch_nintendo", t0, exit_code=0, extra=f"{len(final_games)} games")


if __name__ == "__main__":
    raise SystemExit(main())
