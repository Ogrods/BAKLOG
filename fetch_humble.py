#!/usr/bin/env python3
"""Fetch Humble Bundle library into games_humble.json.

Uses the saved Humble browser profile (Connections -> Humble Bundle) and the
documented Humble API:
  GET /api/v1/user/order
  GET /api/v1/order/{gamekey}?all_tpkds=true

Emits games-only rows by default (drops ebooks, comics, audiobooks, software).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid
from auth.secrets import profile_dir
from fetchers._authoritative import HUMBLE
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

GAMES_HUMBLE_JSON = Path("games_humble.json")
ORDERS_URL = "https://www.humblebundle.com/api/v1/user/order"
ORDER_DETAIL_URL = "https://www.humblebundle.com/api/v1/order/{gamekey}?all_tpkds=true"
def dump_path() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "humble" / "library_dump.json"
HLTB_DELAY_SEC = 1.0
ORDER_DELAY_SEC = 0.35

_GAME_PLATFORMS = frozenset({"windows", "mac", "linux", "android"})
_GAME_KEY_TYPES = frozenset({
    "steam", "origin", "uplay", "ubisoft", "epic", "gog", "battlenet", "external",
})
_NONGAME_KEY_TYPES = frozenset({
    "ebook", "audiobook", "comic", "software", "soundtrack", "asmjs", "video",
})


@dataclass
class LibraryItem:
    machine_name: str
    name: str
    image_url: str | None
    store_url: str
    gamekey: str
    redeemed: bool | None
    steam_app_id: str | None


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _launch_humble_ctx(*, headless: bool = True):
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir("humble")
    if not profile.exists():
        raise RuntimeError(
            "No saved Humble profile at cache/auth/profiles/humble. "
            "Open the Connections page and connect Humble Bundle first."
        )
    return launch_persistent_profile(str(profile), headless=headless)


def _api_get(ctx, url: str, *, timeout_ms: int = 45_000) -> Any:
    resp = ctx.request.get(url, timeout=timeout_ms)
    if resp.status >= 400:
        raise RuntimeError(f"Humble API {url} returned HTTP {resp.status}")
    return json.loads(resp.text())


def _signed_out(exc: Exception | None = None) -> bool:
    if exc is None:
        return False
    msg = str(exc).lower()
    return "401" in msg or "403" in msg or "sign in" in msg


def _tpk_ids_for_sub(sub: dict) -> list[str]:
    tpks = sub.get("tpks") or {}
    if isinstance(tpks, dict):
        out: list[str] = []
        for v in tpks.values():
            if isinstance(v, list):
                out.extend(str(x) for x in v)
            elif isinstance(v, str):
                out.append(v)
        return out
    if isinstance(tpks, list):
        return [str(x) for x in tpks]
    return []


def _subproduct_is_game(sub: dict, tpkd_dict: dict) -> bool:
    downloads = sub.get("downloads") or []
    if isinstance(downloads, list):
        for dl in downloads:
            if not isinstance(dl, dict):
                continue
            plat = (dl.get("platform") or "").lower()
            if plat in _GAME_PLATFORMS:
                return True
    for tid in _tpk_ids_for_sub(sub):
        tpkd = tpkd_dict.get(tid) if isinstance(tpkd_dict, dict) else None
        if not isinstance(tpkd, dict):
            continue
        kt = (tpkd.get("key_type") or "").lower()
        if kt in _NONGAME_KEY_TYPES:
            continue
        if kt in _GAME_KEY_TYPES or kt == "steam":
            return True
    human = (sub.get("human_name") or "").lower()
    if any(tok in human for tok in ("soundtrack only", "ebook", "audiobook", "comic book")):
        return False
    return False


def _steam_app_from_sub(sub: dict, tpkd_dict: dict) -> str | None:
    for tid in _tpk_ids_for_sub(sub):
        tpkd = tpkd_dict.get(tid) if isinstance(tpkd_dict, dict) else None
        if not isinstance(tpkd, dict):
            continue
        if (tpkd.get("key_type") or "").lower() != "steam":
            continue
        for field in ("steam_app_id", "steam_appid", "steam_id"):
            val = tpkd.get(field)
            if val is not None:
                return str(val)
        m = re.search(r"steam.*?(\d{4,8})", str(tpkd.get("custom_instructions") or ""), re.I)
        if m:
            return m.group(1)
    return None


def _store_url(machine_name: str, steam_app_id: str | None) -> str:
    if steam_app_id:
        return f"https://store.steampowered.com/app/{steam_app_id}"
    slug = quote(machine_name or "", safe="")
    return f"https://www.humblebundle.com/store/{slug}" if slug else "https://www.humblebundle.com/store"


def _parse_order_detail(data: dict, *, include_nongames: bool) -> list[LibraryItem]:
    gamekey = str(data.get("gamekey") or "")
    tpkd_dict = data.get("tpkd_dict") or {}
    if not isinstance(tpkd_dict, dict):
        tpkd_dict = {}
    items: list[LibraryItem] = []
    seen: set[str] = set()
    for sub in data.get("subproducts") or []:
        if not isinstance(sub, dict):
            continue
        if not include_nongames and not _subproduct_is_game(sub, tpkd_dict):
            continue
        machine = str(sub.get("machine_name") or sub.get("custom_download_page_name") or "").strip()
        name = str(sub.get("human_name") or machine or "").strip()
        if not machine and not name:
            continue
        row_id = machine or name
        if row_id in seen:
            continue
        seen.add(row_id)
        icon = sub.get("icon") or sub.get("image")
        image = icon if isinstance(icon, str) and icon.startswith("http") else None
        steam_id = _steam_app_from_sub(sub, tpkd_dict)
        redeemed = sub.get("redeemed")
        if redeemed is None and steam_id:
            redeemed = False
        items.append(
            LibraryItem(
                machine_name=machine or row_id,
                name=name or machine,
                image_url=image,
                store_url=_store_url(machine, steam_id),
                gamekey=gamekey,
                redeemed=redeemed if isinstance(redeemed, bool) else None,
                steam_app_id=steam_id,
            )
        )
    return items


def fetch_library_items(
    *,
    include_nongames: bool = False,
    dump: bool = False,
) -> list[LibraryItem]:
    """Fetch all library items using the saved Humble profile."""
    with _launch_humble_ctx(headless=True) as ctx:
        try:
            orders_raw = _api_get(ctx, ORDERS_URL)
        except Exception as exc:  # noqa: BLE001
            if _signed_out(exc):
                raise RuntimeError("Humble session expired") from exc
            raise

        if not isinstance(orders_raw, list):
            raise RuntimeError("Unexpected Humble orders API response (expected a list)")

        if dump:
            dump_path().parent.mkdir(parents=True, exist_ok=True)
            sample: list[dict] = []
            for entry in orders_raw[:3]:
                if not isinstance(entry, dict):
                    continue
                gk = entry.get("gamekey")
                if not gk:
                    continue
                try:
                    detail = _api_get(ctx, ORDER_DETAIL_URL.format(gamekey=gk))
                    sample.append({"gamekey": gk, "detail": detail})
                except Exception as err:  # noqa: BLE001
                    sample.append({"gamekey": gk, "error": str(err)})
            dump_path().write_text(
                json.dumps(
                    {"order_count": len(orders_raw), "sample_orders": sample},
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"  wrote {dump_path()}", flush=True)
            return []

        found: dict[str, LibraryItem] = {}
        for i, entry in enumerate(orders_raw, 1):
            if not isinstance(entry, dict):
                continue
            gamekey = entry.get("gamekey")
            if not gamekey:
                continue
            print(f"[order {i}/{len(orders_raw)}] {gamekey}", flush=True)
            try:
                detail = _api_get(ctx, ORDER_DETAIL_URL.format(gamekey=gamekey))
            except Exception as exc:  # noqa: BLE001
                print(f"  skip order {gamekey}: {exc}", flush=True)
                time.sleep(ORDER_DELAY_SEC)
                continue
            for item in _parse_order_detail(detail, include_nongames=include_nongames):
                found[item.machine_name] = item
            time.sleep(ORDER_DELAY_SEC)

        return sorted(found.values(), key=lambda x: x.name.lower())


def _build_row(item: LibraryItem, hltb: dict | None) -> dict:
    tags: list[str] = []
    if item.redeemed is False:
        tags.append("unredeemed key")
    if item.steam_app_id:
        tags.append("Steam key")

    return {
        "store": "humble",
        "id": f"humble-{item.machine_name}",
        "humble_id": item.machine_name,
        "humble_gamekey": item.gamekey,
        "humble_steam_app_id": item.steam_app_id,
        "name": item.name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": None,
        "genres": [],
        "tags": tags,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": (hltb or {}).get("hltb_main_hours"),
        "hltb_main_extra_hours": (hltb or {}).get("hltb_main_extra_hours"),
        "hltb_completionist_hours": (hltb or {}).get("hltb_completionist_hours"),
        "hltb_match_confidence": (hltb or {}).get("hltb_match_confidence"),
        "hltb_name": (hltb or {}).get("hltb_name"),
        "store_url": item.store_url,
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }


def _load_existing_by_machine() -> dict[str, dict]:
    if not catalog_file(GAMES_HUMBLE_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_HUMBLE_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    for g in data.get("games", []):
        if isinstance(g, dict) and g.get("humble_id"):
            out[str(g["humble_id"])] = g
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Humble library into games_humble.json")
    parser.add_argument(
        "--skip-hltb",
        action="store_true",
        help="Accepted for manifest/dashboard parity; HLTB is off by default (use --hltb to enable)",
    )
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    parser.add_argument(
        "--include-nongames",
        action="store_true",
        help="Include ebooks, comics, audiobooks, and software (default is games only)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save sample API payloads to {dump_path()} and exit",
    )
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_humble")
    stats = RunStats()
    load_dotenv()

    print("Fetching Humble library via API...", flush=True)
    try:
        items = fetch_library_items(include_nongames=args.include_nongames, dump=args.dump)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "expired" in msg.lower() or "401" in msg or "403" in msg:
            mark_invalid("humble", error=msg)
            stats.error(msg)
            return stats.finish("fetch_humble", t0, exit_code=EXIT_CODE_AUTH)
        stats.error(msg)
        return stats.finish("fetch_humble", t0, exit_code=1)

    if args.dump:
        return stats.finish("fetch_humble", t0, exit_code=0, extra="dump only")

    print(f"  parsed {len(items)} library items", flush=True)

    empty_exit = refuse_empty_result(
        items,
        label="Humble library",
        allow_empty=args.allow_empty,
        output_path=GAMES_HUMBLE_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_humble", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="Humble library",
        allow_drift=args.allow_drift,
        output_path=GAMES_HUMBLE_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_humble", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing_by_machine()
    rows: list[dict] = []
    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {item.name}", flush=True)
        hltb = None
        hltb_updated = False
        cached = existing.get(item.machine_name)
        if hltb_client and item.name:
            if cached and cached.get("hltb_main_hours") is not None:
                hltb = {
                    "hltb_main_hours": cached.get("hltb_main_hours"),
                    "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                    "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                    "hltb_match_confidence": cached.get("hltb_match_confidence"),
                    "hltb_name": cached.get("hltb_name"),
                }
            else:
                try:
                    time.sleep(HLTB_DELAY_SEC)
                    hltb = hltb_client.lookup(item.name)
                    hltb_updated = bool(hltb)
                except Exception as exc:  # noqa: BLE001
                    print(f"  HLTB warning: {exc}", flush=True)
        rows.append(
            merge_cached_row(
                _build_row(item, hltb),
                cached,
                authoritative=HUMBLE,
                hltb_updated=hltb_updated,
            )
        )

    rows = apply_carry_forward(
        rows,
        existing,
        key_fn=row_key_by_id,
        no_carry=args.no_carry,
    )

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "humble",
        "game_count": len(rows),
        "games": rows,
    }
    write_catalog_text(GAMES_HUMBLE_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(rows)} games to {GAMES_HUMBLE_JSON}.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_humble", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    sys.exit(main())
