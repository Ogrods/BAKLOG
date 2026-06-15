#!/usr/bin/env python3
"""Import Amazon library into games_amazon.json (launcher DB or Prime Gaming web)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid
from auth.manager import is_local_provider_disabled, mark_connected
from auth.secrets import profile_dir
from clients.amazon_web_client import AmazonWebAuthError
from fetchers._authoritative import AMAZON

try:
    from amazon_client import AmazonGamesError
except ImportError:
    class AmazonGamesError(Exception):  # type: ignore[no-redef]
        """Stub when amazon_client is unavailable (non-Windows)."""
from clients.hltb_client import HltbClient
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    apply_carry_forward,
    carry_enrichment,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    write_catalog_guarded,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from shared.raw_dumps import profile_raw_dump_path

GAMES_AMAZON_JSON = Path("games_amazon.json")
HLTB_DELAY_SEC = 1.0
AMAZON_WEB_PROFILE = "amazon_web"
# Rows written before per-row source tags are treated as launcher (web is newer).
LEGACY_ROW_SOURCE = "launcher"


AMAZON_RAW_DUMP = profile_raw_dump_path("amazon_web_raw.json")


def _launcher_db_ready(sql_dir: Path | None) -> bool:
    if is_local_provider_disabled("amazon"):
        return False
    if sys.platform != "win32":
        return False
    try:
        from amazon_client import DEFAULT_SQL_DIR, ENTITLEMENTS_DB
    except ImportError:
        return False
    base = sql_dir if sql_dir is not None else DEFAULT_SQL_DIR
    return (Path(base) / ENTITLEMENTS_DB).is_file()


def _web_profile_ready() -> bool:
    prof = profile_dir(AMAZON_WEB_PROFILE)
    if not prof.is_dir():
        return False
    try:
        return any(prof.iterdir())
    except OSError:
        return False


def resolve_source(requested: str, sql_dir: Path | None) -> str:
    src = (requested or "auto").strip().lower()
    if src not in ("auto", "launcher", "web"):
        raise ValueError(f"unknown --source {requested!r}")
    if src != "auto":
        return src
    if _launcher_db_ready(sql_dir):
        return "launcher"
    if _web_profile_ready():
        return "web"
    if sys.platform == "win32":
        raise RuntimeError(
            "Amazon Games launcher database not found and no Prime Gaming web session saved.\n"
            "Install/sign in to the Amazon Games app on this PC, or connect "
            "“Amazon (Prime Gaming, web)” on the Connections page."
        )
    raise RuntimeError(
        "Prime Gaming web session not found. Connect “Amazon (Prime Gaming, web)” "
        "on the Connections page (works on macOS/Linux)."
    )


def _effective_row_source(row: dict) -> str:
    """Per-row source tag; legacy rows without a tag count as launcher."""
    s = row.get("source")
    if s in ("launcher", "web"):
        return str(s)
    return LEGACY_ROW_SOURCE


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _match_key(row: dict) -> str:
    asin = row.get("asin")
    if asin and str(asin).strip():
        return f"asin:{str(asin).strip().lower()}"
    name = _normalize_name(str(row.get("name") or ""))
    if name:
        return f"name:{name}"
    return f"id:{row.get('id')}"


def _source_priority(source: str) -> int:
    return 2 if source == "launcher" else 1


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


def merge_amazon_sources(
    current_rows: list[dict],
    carried_rows: list[dict],
    current_source: str,
) -> list[dict]:
    """Union launcher + web slices; collapse cross-source dupes (ASIN, then name)."""
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


def refuse_amazon_source_drift(
    new_same_source_count: int,
    *,
    source: str,
    allow_drift: bool,
    output_path: Path,
    threshold: float = 0.5,
) -> int | None:
    """Drift guard for the current source slice only (not combined file size)."""
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
        f"ERROR: Amazon {source} slice returned {new_same_source_count} rows, but the "
        f"previous {source} slice had {prev} (≈{pct:.0f}% — under the "
        f"{int(threshold * 100)}% floor).\n"
        "Likely a broken auth or upstream API. If this drop is real, re-run with --allow-drift.",
        file=sys.stderr,
        flush=True,
    )
    return 3


def _build_row(rec: dict, hltb: dict | None, source: str) -> dict:
    pid = rec["amazon_product_id"]
    row = {
        "store": "amazon",
        "id": pid,
        "amazon_id": pid,
        "amazon_entitlement_id": rec.get("amazon_entitlement_id"),
        "amazon_adg_id": rec.get("amazon_adg_id"),
        "name": rec["name"],
        "source": source,
        "playtime_minutes": 0,
        "last_played": rec.get("last_played"),
        "header_image": rec.get("header_image"),
        "library_image": rec.get("library_image"),
        "release_date": rec.get("release_date"),
        "genres": rec.get("genres") or [],
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
        "asin": rec.get("asin"),
        "product_line": rec.get("product_line"),
        "publisher": rec.get("publisher"),
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
    if not catalog_file(GAMES_AMAZON_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_AMAZON_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _load_launcher_records(sql_dir: Path | None) -> list[dict]:
    from amazon_client import AmazonGamesClient

    client = AmazonGamesClient(sql_dir)
    print(f"Reading Amazon Games library from:\n  {client.sql_dir}", flush=True)
    return client.get_library_records()


def _read_raw_dump_claims(*, path: Path) -> list[dict] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    raw_claims = data.get("raw_claims")
    if not isinstance(raw_claims, list):
        return None
    return [c for c in raw_claims if isinstance(c, dict)]


def _web_outcome_kind_from_capture(
    *,
    raw_claims: list[dict],
    outcome: dict,
    fallback_claims: list[dict] | None = None,
) -> str | None:
    """Pure mapping for tests / clearer handling.

    outcome is the dict returned by amazon_web_client.sniff_claims().
    """

    capture_ok = bool(outcome.get("capture_ok"))
    signed_in = bool(outcome.get("signed_in"))

    if capture_ok:
        # claims payload parsed successfully (even if raw_claims == []).
        return "signed_in_empty" if not raw_claims else "signed_in_captured"

    if not signed_in:
        return None  # signed out should be handled via AmazonWebAuthError earlier

    # signed-in but no live claims; caller may supply raw-dump fallback.
    if fallback_claims is not None:
        return "signed_in_empty" if not fallback_claims else "raw_dump_fallback"

    return "signed_in_no_claims"


def _load_web_records(*, dump_raw: bool) -> tuple[list[dict], str | None]:
    """Return (records, web_outcome_kind).

    web_outcome_kind is used so we can distinguish:
    - signed-in-empty (claims payload captured but empty)
    - signed-in-no-claims (headless parse failed; try raw-dump fallback)
    """

    from amazon_web_client import (
        filter_codeless_claims,
        raw_dump_max_age_s,
        raw_dump_path,
        sniff_claims,
    )

    dump = AMAZON_RAW_DUMP if dump_raw else None

    try:
        raw_claims, records, outcome = sniff_claims(dump_path=dump)
    except AmazonWebAuthError as e:
        mark_invalid(AMAZON_WEB_PROFILE, error=str(e))
        raise

    print(
        "Reading Prime Gaming claims (Amazon-fulfilled only, no external keys).",
        flush=True,
    )

    if dump_raw and dump is not None:
        print(f"Wrote raw claims dump to {dump}.", flush=True)

    if outcome.get("capture_ok"):
        # Signed-in + claims payload parsed successfully (including empty list).
        if not raw_claims:
            return [], "signed_in_empty"
        return records, "signed_in_captured"

    # Signed-in, but live capture returned nothing: try raw-dump fallback.
    # (We purposely do NOT overwrite the connect-time fallback dump unless
    # --dump-raw was explicitly requested.)
    if outcome.get("signed_in"):
        raw_path = raw_dump_path()
        max_age_s = raw_dump_max_age_s()
        try:
            age_s = time.time() - raw_path.stat().st_mtime
        except OSError:
            age_s = None
        if age_s is not None and age_s <= max_age_s:
            fallback_claims = _read_raw_dump_claims(path=raw_path)
            if fallback_claims is not None:
                fallback_records = filter_codeless_claims(fallback_claims)
                if not fallback_claims:
                    return [], "signed_in_empty"
                return fallback_records, "raw_dump_fallback"

        return [], "signed_in_no_claims"

    # Should be unreachable: sniff_claims raises AmazonWebAuthError for signed-out.
    return records, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Amazon library (Windows launcher DB or Prime Gaming web)"
    )
    parser.add_argument(
        "--source",
        choices=("auto", "launcher", "web"),
        default=os.getenv("AMAZON_SOURCE", "auto").strip().lower() or "auto",
        help="auto: launcher DB on Windows when present, else web profile (default: auto)",
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=None,
        help="Override Amazon Games Sql folder (launcher source only)",
    )
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="Only HLTB-fetch games missing HLTB data",
    )
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=f"Web source only: write {AMAZON_RAW_DUMP} with full claims payload",
    )
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_amazon")
    stats = RunStats()
    load_dotenv()

    sql_dir = args.sql_dir
    if sql_dir is None:
        env_dir = os.getenv("AMAZON_GAMES_SQL_DIR", "").strip()
        sql_dir = Path(env_dir) if env_dir else None

    try:
        source = resolve_source(args.source, sql_dir)
    except (RuntimeError, ValueError) as e:
        stats.error(str(e))
        return stats.finish("fetch_amazon", t0, exit_code=1)

    print(f"Amazon source: {source}", flush=True)

    try:
        web_outcome_kind: str | None = None
        if source == "launcher":
            if sys.platform != "win32":
                stats.error("Launcher source requires Windows (DPAPI). Use --source web.")
                return stats.finish("fetch_amazon", t0, exit_code=1)
            records = _load_launcher_records(sql_dir)
        else:
            records, web_outcome_kind = _load_web_records(dump_raw=args.dump_raw)
    except ImportError as e:
        stats.error(str(e))
        return stats.finish("fetch_amazon", t0, exit_code=1)
    except AmazonWebAuthError as e:
        stats.error(str(e))
        return stats.finish("fetch_amazon", t0, exit_code=EXIT_CODE_AUTH)
    except AmazonGamesError as e:
        stats.error(str(e))
        return stats.finish("fetch_amazon", t0, exit_code=1)
    except Exception as e:
        stats.error(str(e))
        return stats.finish("fetch_amazon", t0, exit_code=1)

    if not records:
        if web_outcome_kind == "signed_in_empty":
            print("Prime Gaming web: collection is empty (claims payload captured).", flush=True)
        else:
            stats.error("No Amazon games found for the selected source.")
            return stats.finish("fetch_amazon", t0, exit_code=2)

    print(f"Found {len(records)} Amazon titles.", flush=True)

    hltb_client = HltbClient()
    existing = load_existing()
    carried_rows = [
        row
        for row in existing.values()
        if _effective_row_source(row) != source
    ]
    if carried_rows:
        print(
            f"Keeping {len(carried_rows)} row(s) from the other Amazon source.",
            flush=True,
        )

    current_rows: list[dict] = []

    for i, rec in enumerate(records, 1):
        pid = rec["amazon_product_id"]
        name = rec["name"]
        print(f"[{i}/{len(records)}] {name}", flush=True)

        cached = existing.get(pid)
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
        elif cached:
            hltb = {
                "hltb_main_hours": cached.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached.get("hltb_match_confidence"),
                "hltb_name": cached.get("hltb_name"),
            }

        current_rows.append(
            merge_cached_row(
                _build_row(rec, hltb, source),
                cached,
                authoritative=AMAZON,
                hltb_updated=hltb_updated,
            )
        )

    drift_exit = None
    if not (source == "web" and web_outcome_kind == "signed_in_empty"):
        drift_exit = refuse_amazon_source_drift(
            len(current_rows),
            source=source,
            allow_drift=args.allow_drift,
            output_path=GAMES_AMAZON_JSON,
        )
        if drift_exit is not None:
            return stats.finish("fetch_amazon", t0, exit_code=drift_exit)

    games_out = merge_amazon_sources(current_rows, carried_rows, source)

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=_match_key,
        no_carry=args.no_carry,
    )

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "amazon",
        "source": source,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    # Route the write through the shared guard. Per-source drift was already
    # enforced above (refuse_amazon_source_drift), so the file-level drift guard
    # is disabled here — the union file legitimately grows/shrinks across two
    # sources — but the empty guard still protects the merged catalog. A
    # genuinely empty signed-in Prime collection is allowed through.
    guard_allow_empty = args.allow_empty or (
        source == "web" and web_outcome_kind == "signed_in_empty"
    )
    refused = write_catalog_guarded(
        GAMES_AMAZON_JSON,
        json.dumps(payload, indent=2, ensure_ascii=False),
        count=games_out,
        label="Amazon library",
        allow_empty=guard_allow_empty,
        allow_drift=True,
    )
    if refused:
        return stats.finish("fetch_amazon", t0, exit_code=refused)
    if source == "web":
        mark_connected(AMAZON_WEB_PROFILE, {"AMAZON_WEB_PROFILE": "ready"})
    print(f"\nWrote {len(games_out)} games to {GAMES_AMAZON_JSON}.", flush=True)
    print("Reload the dashboard to see your Amazon library.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_amazon", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
