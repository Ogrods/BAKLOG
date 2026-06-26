#!/usr/bin/env python3
"""Fetch GOG library data and write games_gog.json for the dashboard."""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from auth.manager import is_local_provider_disabled, mark_connected
from auth.session_probe import probe_gog_session
from clients.gog_client import GOG_AUTH_MESSAGE, GogAuthError, GogClient
from clients.gog_filters import apply_gog_name_filters, filter_gog_game_rows
from clients.hltb_client import HltbClient
from fetchers._authoritative import GOG
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    apply_carry_forward,
    carry_enrichment,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    refuse_empty_result,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from shared.library_noise import catalog_game_count, maybe_tag_library_noise_row

GAMES_GOG_JSON = Path("games_gog.json")
HLTB_DELAY_SEC = 1.0
GOG_WEB_DETAIL_WORKERS = 6
LEGACY_ROW_SOURCE = "web"

# Stable metadata that the other GOG source may have populated (web has release_date;
# local Galaxy DB often does not). Carried on source flip after merge_cached_row.
_GOG_CROSS_SOURCE_CARRY = ("release_date", "genres", "header_image", "library_image", "tags")


def _needs_product_details(args, cached_row: dict | None) -> bool:
    """Whether the web fetch path should call gameDetails for this row."""
    if args.refresh or cached_row is None or args.gog_id:
        return True
    return not (cached_row.get("genres") or [])


def _gog_image_urls(raw: str | None) -> tuple[str | None, str | None]:
    """Turn GOG's bare image hash into usable (header, library_cover) URLs.

    GOG's CDN serves the hash without a file extension; the bare path 404s.
    Append `.jpg` for the original (landscape banner) and `_glx_vertical_cover.jpg`
    for the portrait cover used by Galaxy. The HTML img onerror handler falls
    back to the header if the vertical cover doesn't exist for older titles.
    """
    if not raw:
        return None, None
    url = raw
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return None, None
    if url.endswith(".jpg") or url.endswith(".png"):
        return url, url
    return f"{url}.jpg", f"{url}_glx_vertical_cover.jpg"


def _normalize_gog_store_url(product: dict, gog_id: int) -> str:
    """GOG API often returns a site-relative path; the dashboard needs an absolute URL."""
    url = (product.get("url") or "").strip()
    slug = product.get("slug") or str(gog_id)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.gog.com{url}"
    if url:
        return f"https://www.gog.com/{url.lstrip('/')}"
    return f"https://www.gog.com/en/game/{slug}"


def _extract_genres(product: dict, details: dict | None) -> list[str]:
    genres: list[str] = []
    for source in (details or {}, product):
        for key in ("genres", "tags"):
            raw = source.get(key)
            if not raw:
                continue
            for g in raw:
                if isinstance(g, str):
                    genres.append(g)
                elif isinstance(g, dict):
                    label = g.get("name") or g.get("title") or g.get("slug")
                    if label:
                        genres.append(str(label))
    return list(dict.fromkeys(genres))


def _playtime_minutes(details: dict | None) -> int:
    if not details:
        return 0
    for key in ("playTime", "playtime", "timePlayed"):
        val = details.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            return int(val // 60) if val > 500 else int(val)
        if isinstance(val, dict):
            mins = val.get("minutes") or val.get("total") or 0
            return int(mins)
    return 0


def _build_game_row(
    product: dict,
    details: dict | None,
    hltb: dict | None,
) -> dict | None:
    gog_id = int(product.get("id") or product.get("productId") or 0)
    if not gog_id:
        return None

    media_type = product.get("mediaType") or product.get("media_type")
    if media_type not in (None, 1, "1", "game"):
        return None

    name = (
        product.get("title")
        or product.get("name")
        or (details or {}).get("title")
        or f"GOG {gog_id}"
    )
    image = (
        product.get("image")
        or product.get("img")
        or (details or {}).get("backgroundImage")
        or (details or {}).get("image")
    )
    header_url, library_url = _gog_image_urls(image)

    release = product.get("releaseDate") or product.get("release_date")
    if isinstance(release, dict):
        release = release.get("date") or release.get("title")

    price_block = product.get("price") or {}
    if isinstance(price_block, dict):
        final_price = price_block.get("finalAmount") or price_block.get("final")
        currency = price_block.get("currency") or product.get("currency")
        discount = price_block.get("discount") or price_block.get("discountPercent")
        price_str = None
        if final_price is not None and currency:
            price_str = f"{final_price} {currency}"
    else:
        price_str = None
        currency = None
        discount = None

    row = {
        "store": "gog",
        "id": gog_id,
        "gog_id": gog_id,
        "name": name,
        "playtime_minutes": _playtime_minutes(details),
        "last_played": None,
        "header_image": header_url,
        "library_image": library_url,
        "release_date": release,
        "genres": _extract_genres(product, details),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _normalize_gog_store_url(product, gog_id),
        "type": "game",
        "price": price_str,
        "price_initial": None,
        "discount_percent": discount,
        "currency": currency,
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

    maybe_tag_library_noise_row(row, "gog")
    return row


def _effective_row_source(row: dict) -> str:
    s = row.get("source")
    if s in ("local", "web"):
        return str(s)
    return LEGACY_ROW_SOURCE


def _field_empty(value: object) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def merge_gog_cached_row(
    fresh: dict,
    cached: dict | None,
    *,
    source: str,
    hltb_updated: bool = False,
) -> dict:
    """Merge a GOG fetch row onto cache, preserving metadata across source switches."""
    merged = merge_cached_row(
        fresh,
        cached,
        authoritative=GOG,
        hltb_updated=hltb_updated,
    )
    if not cached or _effective_row_source(cached) == source:
        return merged
    merged = carry_enrichment(merged, cached)
    for key in _GOG_CROSS_SOURCE_CARRY:
        if _field_empty(merged.get(key)) and not _field_empty(cached.get(key)):
            merged[key] = cached[key]
    return merged


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _match_key(row: dict) -> str:
    gid = row.get("gog_id") or row.get("id")
    if gid is not None:
        return f"gog_id:{gid}"
    name = _normalize_name(str(row.get("name") or ""))
    if name:
        return f"name:{name}"
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


def merge_gog_sources(
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


def refuse_gog_source_drift(
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
        f"ERROR: GOG {source} slice drift refused — new={new_same_source_count}, "
        f"previous={prev}, floor={floor} (≥{int(threshold * 100)}% of prior), "
        f"ratio≈{pct:.0f}%.\n"
        "Reason: same-source row count fell below the drift guard (broken auth/API, "
        "or a legitimate library shrink from filtering). Re-run with --allow-drift "
        "if the drop is expected.",
        file=sys.stderr,
        flush=True,
    )
    return 3


def _galaxy_db_ready(db_path: Path | None) -> bool:
    if is_local_provider_disabled("gog_galaxy"):
        return False
    from clients.gog_galaxy_client import default_galaxy_db

    path = db_path if db_path is not None else default_galaxy_db()
    return path.is_file()


def _web_creds_ready() -> bool:
    return bool(resolve_env("GOG_AL", provider="gog"))


def _gog_galaxy_hint(db_path: Path | None) -> str:
    if _galaxy_db_ready(db_path):
        return " GOG Galaxy database detected — retry with: python fetch_gog.py --source local"
    return ""


def resolve_source(requested: str, db_path: Path | None) -> str:
    src = (requested or "auto").strip().lower()
    if src not in ("auto", "web", "local"):
        raise ValueError(f"unknown --source {requested!r}")
    if src != "auto":
        return src
    if _galaxy_db_ready(db_path):
        return "local"
    if _web_creds_ready():
        return "web"
    raise RuntimeError(
        "GOG Galaxy database not found and no GOG web session saved.\n"
        "Install/sign in to GOG Galaxy on this PC, or connect GOG on the Connections page."
    )


def _build_game_row_from_local(rec: dict, hltb: dict | None, source: str) -> dict:
    gog_id = int(rec["gog_id"])
    header_url, library_url = _gog_image_urls(
        rec.get("raw_image") or rec.get("header_image")
    )
    row = {
        "store": "gog",
        "id": gog_id,
        "gog_id": gog_id,
        "name": rec["name"],
        "source": source,
        "playtime_minutes": 0,
        "last_played": rec.get("last_played"),
        "header_image": header_url,
        "library_image": library_url,
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
        "store_url": rec.get("store_url") or f"https://www.gog.com/en/game/{gog_id}",
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
    maybe_tag_library_noise_row(row, "gog")
    return row


def _load_local_records(db_path: Path | None) -> list[dict]:
    from clients.gog_galaxy_client import GogGalaxyClient

    client = GogGalaxyClient(db_path)
    print(f"Reading GOG library from Galaxy database:\n  {client.db_path}", flush=True)
    return client.get_library_records()


def load_existing() -> dict[int, dict]:
    if not catalog_file(GAMES_GOG_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_GOG_JSON).read_text(encoding="utf-8"))
    return {g["id"]: g for g in data.get("games", [])}


def _tag_web_row(row: dict) -> dict:
    row = dict(row)
    row["source"] = "web"
    return row


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch GOG library (Galaxy local DB or web cookie)"
    )
    parser.add_argument(
        "--source",
        choices=("auto", "web", "local"),
        default=os.getenv("GOG_SOURCE", "auto").strip().lower() or "auto",
        help="auto: Galaxy DB when present, else web cookie (default: auto)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override GOG Galaxy galaxy-2.0.db path (local source only)",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore API cache (web)")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_gog.json")
    parser.add_argument("--id", type=int, dest="gog_id", help="Fetch a single product by GOG ID")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_gog")
    stats = RunStats()
    load_dotenv()

    db_path = args.db_path
    if db_path is None:
        env_db = os.getenv("GOG_GALAXY_DB", "").strip()
        db_path = Path(env_db) if env_db else None
    if db_path is not None and not db_path.is_file():
        db_path = None  # ignore stale sentinel / bad override; use default Galaxy path

    try:
        source = resolve_source(args.source, db_path)
    except (RuntimeError, ValueError) as e:
        stats.error(str(e))
        return stats.finish("fetch_gog", t0, exit_code=1)

    print(f"GOG source: {source}", flush=True)

    hltb_client = HltbClient()
    existing = load_existing()
    carried_rows = [
        row
        for row in existing.values()
        if _effective_row_source(row) != source
    ]
    if carried_rows:
        print(
            f"Keeping {len(carried_rows)} row(s) from the other GOG source.",
            flush=True,
        )

    current_rows: list[dict] = []

    if source == "local":
        try:
            from clients.gog_galaxy_client import GogGalaxyError

            records = _load_local_records(db_path)
        except ImportError as e:
            stats.error(str(e))
            return stats.finish("fetch_gog", t0, exit_code=1)
        except GogGalaxyError as e:
            stats.error(str(e))
            return stats.finish("fetch_gog", t0, exit_code=1)

        empty_exit = refuse_empty_result(
            records,
            label="GOG Galaxy library",
            allow_empty=args.allow_empty,
            output_path=GAMES_GOG_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_gog", t0, exit_code=empty_exit)

        print(f"Found {len(records)} GOG titles in Galaxy.", flush=True)

        if args.gog_id:
            records = [r for r in records if r["gog_id"] == args.gog_id]

        for i, rec in enumerate(records, 1):
            gog_id = rec["gog_id"]
            name = rec["name"]
            print(f"[{i}/{len(records)}] {name} ({gog_id})", flush=True)

            cached = existing.get(gog_id)

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
                merge_gog_cached_row(
                    _build_game_row_from_local(rec, hltb, source),
                    cached,
                    source=source,
                    hltb_updated=hltb_updated,
                )
            )
    else:
        gog_al = resolve_env("GOG_AL", provider="gog")
        if not gog_al:
            stats.error("Set GOG_AL in .env or connect GOG on the Connections page.")
            return stats.finish("fetch_gog", t0, exit_code=1)

        probe_err = probe_gog_session(gog_al)
        if probe_err:
            msg = probe_err + _gog_galaxy_hint(db_path)
            mark_invalid("gog", error=msg)
            stats.error(msg)
            return stats.finish("fetch_gog", t0, exit_code=EXIT_CODE_AUTH)

        gog = GogClient(gog_al)
        print("Fetching owned games from GOG (web)...", flush=True)
        try:
            products = gog.get_all_filtered_products(refresh=args.refresh)
        except GogAuthError:
            print(
                "GOG library API rejected the session; trying owned-game ID list...",
                flush=True,
            )
            products = None
            try:
                owned_ids = run_with_heartbeat(gog.get_owned_game_ids, "GOG owned IDs")
            except GogAuthError:
                owned_ids = []
            if owned_ids:
                print(
                    f"Warning: degraded fetch via per-game details ({len(owned_ids)} IDs).",
                    flush=True,
                )
                products = [{"id": pid, "title": f"GOG {pid}"} for pid in owned_ids]
            if products is None:
                msg = GOG_AUTH_MESSAGE + _gog_galaxy_hint(db_path)
                mark_invalid("gog", error=msg)
                stats.error(msg)
                return stats.finish("fetch_gog", t0, exit_code=EXIT_CODE_AUTH)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                msg = GOG_AUTH_MESSAGE + _gog_galaxy_hint(db_path)
                mark_invalid("gog", error=msg)
                stats.error(msg)
                return stats.finish("fetch_gog", t0, exit_code=EXIT_CODE_AUTH)
            stats.error(f"GOG library API HTTP error: {e}")
            return stats.finish("fetch_gog", t0, exit_code=1)

        if not products:
            owned_ids = run_with_heartbeat(gog.get_owned_game_ids, "GOG owned IDs")
            print(f"Found {len(owned_ids)} owned IDs (building from details)...", flush=True)
            products = [{"id": pid, "title": f"GOG {pid}"} for pid in owned_ids]
        else:
            print(f"Found {len(products)} products in library.", flush=True)

        empty_exit = refuse_empty_result(
            products,
            label="GOG library",
            allow_empty=args.allow_empty,
            output_path=GAMES_GOG_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_gog", t0, exit_code=empty_exit)

        if args.gog_id:
            products = [
                p
                for p in products
                if int(p.get("id") or p.get("productId") or 0) == args.gog_id
            ]
            if not products:
                products = [{"id": args.gog_id, "title": f"GOG {args.gog_id}"}]

        skipped = 0
        details_by_id: dict[int, dict | None] = {}
        if source == "web":
            detail_ids: list[int] = []
            for product in products:
                gog_id = int(product.get("id") or product.get("productId") or 0)
                if args.only_new and gog_id in existing and not args.refresh and not args.gog_id:
                    row = existing.get(gog_id)
                    if row and _effective_row_source(row) == source:
                        continue
                cached_row = existing.get(gog_id)
                if _needs_product_details(args, cached_row):
                    detail_ids.append(gog_id)
            if detail_ids:
                def _fetch_detail(pid: int) -> tuple[int, dict | None]:
                    try:
                        return pid, gog.get_product_details(pid, refresh=args.refresh)
                    except Exception:  # noqa: BLE001
                        return pid, None

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=GOG_WEB_DETAIL_WORKERS
                ) as ex:
                    futures = [ex.submit(_fetch_detail, pid) for pid in detail_ids]
                    for fut in concurrent.futures.as_completed(futures):
                        pid, det = fut.result()
                        details_by_id[pid] = det

        for i, product in enumerate(products, 1):
            gog_id = int(product.get("id") or product.get("productId") or 0)
            name = product.get("title") or product.get("name") or str(gog_id)

            if args.only_new and gog_id in existing and not args.refresh and not args.gog_id:
                row = existing[gog_id]
                if _effective_row_source(row) == source:
                    current_rows.append(row)
                continue

            print(f"[{i}/{len(products)}] {name} ({gog_id})", flush=True)

            cached_row = existing.get(gog_id)

            need_details = _needs_product_details(args, cached_row)
            details = details_by_id.get(gog_id) if source == "web" else None
            if need_details and details is None and source != "web":
                try:
                    details = gog.get_product_details(gog_id, refresh=args.refresh)
                except Exception as e:
                    print(f"  Details warning: {e}", flush=True)
            elif need_details and source == "web" and gog_id not in details_by_id:
                try:
                    details = gog.get_product_details(gog_id, refresh=args.refresh)
                except Exception as e:
                    print(f"  Details warning: {e}", flush=True)

            hltb = None
            hltb_updated = False
            if not args.skip_hltb and (
                args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None
            ):
                try:
                    time.sleep(HLTB_DELAY_SEC)
                    hltb = hltb_client.lookup(name)
                    hltb_updated = bool(hltb)
                except Exception as e:
                    print(f"  HLTB warning: {e}", flush=True)
            elif cached_row:
                hltb = {
                    "hltb_main_hours": cached_row.get("hltb_main_hours"),
                    "hltb_main_extra_hours": cached_row.get("hltb_main_extra_hours"),
                    "hltb_completionist_hours": cached_row.get("hltb_completionist_hours"),
                    "hltb_match_confidence": cached_row.get("hltb_match_confidence"),
                    "hltb_name": cached_row.get("hltb_name"),
                }

            row = _build_game_row(product, details, hltb)
            if row is None:
                skipped += 1
                continue
            current_rows.append(
                merge_gog_cached_row(
                    _tag_web_row(row),
                    cached_row,
                    source=source,
                    hltb_updated=hltb_updated,
                )
            )
        if skipped:
            print(f"Skipped {skipped} non-game items.", flush=True)

        before = len(current_rows)
        current_rows = apply_gog_name_filters(current_rows)
        collapsed = before - len(current_rows)
        if collapsed:
            print(
                f"Collapsed {collapsed} promo/pack duplicate(s) on web slice.",
                flush=True,
            )

    drift_exit = refuse_gog_source_drift(
        len(current_rows),
        source=source,
        allow_drift=args.allow_drift,
        output_path=GAMES_GOG_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_gog", t0, exit_code=drift_exit)

    games_out = merge_gog_sources(current_rows, carried_rows, source)
    before_merge = len(games_out)
    games_out = filter_gog_game_rows(games_out)
    if len(games_out) < before_merge:
        print(
            f"Post-merge: dropped {before_merge - len(games_out)} pack/promo "
            "duplicate(s) across mixed gog_id sources.",
            flush=True,
        )

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=_match_key,
        no_carry=args.no_carry,
    )

    for row in games_out:
        maybe_tag_library_noise_row(row, "gog")

    playable = catalog_game_count(games_out)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "gog",
        "source": source,
        "game_count": playable,
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    write_catalog_text(GAMES_GOG_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    if source == "local":
        mark_connected("gog_galaxy", {})
    print(f"\nWrote {playable} games to {GAMES_GOG_JSON}.", flush=True)
    print("Open index.html in your browser to view the dashboard.", flush=True)
    stats.ok = playable
    return stats.finish("fetch_gog", t0, exit_code=0, extra=f"{playable} games")


if __name__ == "__main__":
    raise SystemExit(main())
