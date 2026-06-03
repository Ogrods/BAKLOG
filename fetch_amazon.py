#!/usr/bin/env python3
"""Import Amazon library into games_amazon.json (launcher DB or Prime Gaming web)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_connected, mark_invalid
from auth.secrets import profile_dir
from amazon_web_client import AmazonWebAuthError
from fetchers._authoritative import AMAZON

try:
    from amazon_client import AmazonGamesError
except ImportError:
    class AmazonGamesError(Exception):  # type: ignore[no-redef]
        """Stub when amazon_client is unavailable (non-Windows)."""
from fetchers._base import add_allow_empty_arg, merge_cached_row, refuse_drift_result, catalog_file, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient

GAMES_AMAZON_JSON = Path("games_amazon.json")


def raw_dump_json() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "amazon_web_raw.json"
HLTB_DELAY_SEC = 1.0
AMAZON_WEB_PROFILE = "amazon_web"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _launcher_db_ready(sql_dir: Path | None) -> bool:
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


def _build_row(rec: dict, hltb: dict | None) -> dict:
    pid = rec["amazon_product_id"]
    row = {
        "store": "amazon",
        "id": pid,
        "amazon_id": pid,
        "amazon_entitlement_id": rec.get("amazon_entitlement_id"),
        "amazon_adg_id": rec.get("amazon_adg_id"),
        "name": rec["name"],
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
    from amazon_client import AmazonGamesClient, AmazonGamesError

    client = AmazonGamesClient(sql_dir)
    print(f"Reading Amazon Games library from:\n  {client.sql_dir}", flush=True)
    return client.get_library_records()


def _load_web_records(*, dump_raw: bool) -> list[dict]:
    from amazon_web_client import AmazonWebAuthError, AmazonWebClient, sniff_claims

    dump = raw_dump_json() if dump_raw else None
    try:
        if dump_raw:
            _raw, records = sniff_claims(dump_path=dump)
            print(f"Wrote raw claims dump to {dump}.", flush=True)
        else:
            records = AmazonWebClient().get_library_records()
    except AmazonWebAuthError as e:
        mark_invalid(AMAZON_WEB_PROFILE, error=str(e))
        raise
    print(
        "Reading Prime Gaming claims (Amazon-fulfilled only, no external keys).",
        flush=True,
    )
    return records


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
    parser.add_argument("--only-new", action="store_true", help="Only HLTB-fetch games missing HLTB data")
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help="Web source only: write cache/amazon_web_raw.json with full claims payload",
    )
    parser.add_argument("--allow-drift", action="store_true")
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
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
        if source == "launcher":
            if sys.platform != "win32":
                stats.error("Launcher source requires Windows (DPAPI). Use --source web.")
                return stats.finish("fetch_amazon", t0, exit_code=1)
            records = _load_launcher_records(sql_dir)
        else:
            records = _load_web_records(dump_raw=args.dump_raw)
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
        stats.error("No Amazon games found for the selected source.")
        return stats.finish("fetch_amazon", t0, exit_code=2)

    print(f"Found {len(records)} Amazon titles.", flush=True)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []

    for i, rec in enumerate(records, 1):
        pid = rec["amazon_product_id"]
        name = rec["name"]
        print(f"[{i}/{len(records)}] {name}", flush=True)

        cached = existing.get(pid)
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

        games_out.append(
            merge_cached_row(
                _build_row(rec, hltb),
                cached,
                authoritative=AMAZON,
                hltb_updated=hltb_updated,
            )
        )

    drift_exit = refuse_drift_result(
        games_out,
        label="Amazon library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_AMAZON_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_amazon", t0, exit_code=drift_exit)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "amazon",
        "source": source,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_AMAZON_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    if source == "web":
        mark_connected(AMAZON_WEB_PROFILE, {"AMAZON_WEB_PROFILE": "ready"})
    print(f"\nWrote {len(games_out)} games to {GAMES_AMAZON_JSON}.", flush=True)
    print("Reload the dashboard to see your Amazon library.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_amazon", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
