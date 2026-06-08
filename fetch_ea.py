#!/usr/bin/env python3
"""Fetch EA App library via Juno GraphQL (unofficial)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_connected, mark_invalid, resolve_env
from auth.secrets import profile_dir
from ea_client import (
    EA_PLAY_OWNERSHIP,
    REAL_OWNERSHIP,
    XGP_ONLY,
    EaAuthError,
    EaCaptureError,
    EaClient,
)
from ea_session import DEFAULT_TRIGGER_URLS, probe_ea_token, sniff_ea_bearer
from fetchers._authoritative import EA
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
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from hltb_client import HltbClient
from shared.raw_dumps import profile_raw_dump_path

GAMES_EA_JSON = Path("games_ea.json")


EA_RAW_DUMP = profile_raw_dump_path("ea_raw.json")


def fetch_debug_json() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "ea" / "fetch_debug.json"


HLTB_DELAY_SEC = 1.0

_TM_CHARS = "".maketrans({"®": "", "™": "", "©": ""})


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").translate(_TM_CHARS).split()).strip()


def _ea_connected() -> bool:
    prof = profile_dir("ea")
    if prof.exists() and any(prof.iterdir()):
        return True
    return bool(resolve_env("EA_BEARER_TOKEN", provider="ea"))


def _resolve_session(
    *,
    headless: bool,
    timeout_s: int = 45,
    dump_debug: bool = False,
) -> tuple[str, list[dict], dict[str, Any]]:
    """Return (bearer_token, cookies, debug_info)."""
    debug: dict[str, Any] = {"headless": headless, "stored_token_probe": None}
    stored = (resolve_env("EA_BEARER_TOKEN", provider="ea") or "").strip()

    if stored:
        probe = probe_ea_token(stored)
        debug["stored_token_probe"] = probe
        if probe.get("ok"):
            debug["token_source"] = "stored"
            return stored, [], debug

    profile = profile_dir("ea")
    if not profile.exists() or not any(profile.iterdir()):
        raise EaAuthError(
            "No saved EA profile at cache/auth/profiles/ea. "
            "Open the Connections page and connect EA App first."
        )

    from auth.cdp_browser import launch_persistent_profile

    with launch_persistent_profile(str(profile), headless=headless) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            result = sniff_ea_bearer(
                ctx,
                page,
                trigger_urls=DEFAULT_TRIGGER_URLS,
                timeout_s=timeout_s,
                debug_out=debug,
            )
        except (EaAuthError, EaCaptureError):
            if dump_debug:
                _write_fetch_debug(debug, page=page)
            raise
        debug.update(result.debug)
        debug["token_source"] = "sniff"
        if dump_debug:
            debug["final_url"] = result.debug.get("final_url")
            _write_fetch_debug(debug, page=page)
        mark_connected(
            "ea",
            {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": result.token},
        )
        return result.token, result.cookies, debug


def _write_fetch_debug(debug: dict[str, Any], *, page: Any = None) -> None:
    path = fetch_debug_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    if page is not None:
        try:
            debug.setdefault("final_url", getattr(page, "url", None) or "")
        except Exception:  # noqa: BLE001
            pass
    path.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")


def _ownership_methods(item: dict) -> set[str]:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    gpu = product.get("gameProductUser") if isinstance(product.get("gameProductUser"), dict) else {}
    methods = gpu.get("ownershipMethods") or []
    return {str(m) for m in methods if m}


def _should_include(item: dict) -> bool:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    base = product.get("baseItem") if isinstance(product.get("baseItem"), dict) else {}
    if base.get("isLauncher"):
        return False
    game_type = (base.get("gameType") or "").upper()
    if game_type and game_type not in ("GAME", "BASE_GAME", "FULL_GAME", ""):
        if game_type in ("DEMO", "TRIAL", "TOOL", "LAUNCHER"):
            return False
    methods = _ownership_methods(item)
    if methods and methods <= XGP_ONLY:
        return False
    name = _clean_name(str(product.get("name") or ""))
    return bool(name)


def _tags_for(item: dict) -> list[str]:
    methods = _ownership_methods(item)
    tags: list[str] = []
    if methods & EA_PLAY_OWNERSHIP and not (methods & REAL_OWNERSHIP):
        tags.append("ea_play")
    if methods & XGP_ONLY:
        tags.append("game-pass")
    return tags


def _store_url(item: dict, name: str) -> str:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    slug = product.get("gameSlug")
    if isinstance(slug, str) and slug.strip():
        return f"https://www.ea.com/games/{quote(slug.strip(), safe='')}"
    return f"https://www.ea.com/search?q={quote(name)}"


def _row_id(item: dict) -> str:
    offer = item.get("originOfferId") or item.get("id")
    if offer:
        return str(offer)
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    pid = product.get("id")
    if pid:
        return str(pid)
    return "ea-unknown"


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_EA_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_EA_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(
    item: dict,
    *,
    hltb: dict | None,
    play_by_slug: dict[str, dict],
) -> dict:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    name = _clean_name(str(product.get("name") or "")) or "Unknown EA title"
    rid = _row_id(item)
    slug = product.get("gameSlug")
    play = play_by_slug.get(slug) if isinstance(slug, str) else None
    playtime_minutes = None
    last_played = None
    if isinstance(play, dict):
        secs = play.get("totalPlayTimeSeconds")
        if isinstance(secs, (int, float)) and secs > 0:
            playtime_minutes = int(secs // 60)
        last_played = play.get("lastSessionEndDate") if isinstance(play.get("lastSessionEndDate"), str) else None

    row = {
        "store": "ea",
        "id": rid,
        "ea_id": rid,
        "ea_offer_id": str(item.get("originOfferId") or rid),
        "ea_game_slug": slug if isinstance(slug, str) else None,
        "name": name,
        "playtime_minutes": playtime_minutes,
        "last_played": last_played,
        "header_image": None,
        "library_image": None,
        "release_date": None,
        "genres": [],
        "tags": _tags_for(item),
        "game_pass": bool(_ownership_methods(item) & XGP_ONLY),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _store_url(item, name),
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


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fetch EA App library (unofficial GraphQL)")
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    parser.add_argument("--skip-hltb", action="store_true")
    parser.add_argument("--dump-raw", action="store_true")
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
    _configure_stdout()
    t0 = started("fetch_ea")
    stats = RunStats()

    if not _ea_connected():
        stats.error(
            "EA App is not connected. Open Connections → EA App → Connect and sign in at ea.com."
        )
        return stats.finish("fetch_ea", t0, exit_code=1)

    try:
        token, cookies, _dbg = run_with_heartbeat(
            lambda: _resolve_session(
                headless=not args.headed,
                dump_debug=args.dump_debug,
            ),
            "EA session capture",
        )
    except EaCaptureError as e:
        stats.error(str(e))
        return stats.finish("fetch_ea", t0, exit_code=1)
    except EaAuthError as e:
        mark_invalid("ea", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_ea", t0, exit_code=EXIT_CODE_AUTH)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        is_transport = any(
            tok in msg.lower()
            for tok in ("cdp command timed out", "websocket", "browser", "debugging endpoint")
        )
        if is_transport:
            stats.error(f"EA session capture transport error: {msg}")
            return stats.finish("fetch_ea", t0, exit_code=1)
        mark_invalid("ea", error=msg)
        stats.error(msg)
        return stats.finish("fetch_ea", t0, exit_code=EXIT_CODE_AUTH)

    try:
        client = EaClient(token, cookies=cookies)
        raw_items = client.get_owned_games()
    except EaAuthError as e:
        mark_invalid("ea", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_ea", t0, exit_code=EXIT_CODE_AUTH)

    items = [i for i in raw_items if _should_include(i)]
    seen: dict[str, dict] = {}
    for item in items:
        key = _row_id(item).lower()
        if key not in seen:
            seen[key] = item
    deduped = list(seen.values())
    print(f"Found {len(deduped)} EA titles (from {len(raw_items)} API rows).", flush=True)

    if args.dump_raw:
        EA_RAW_DUMP.parent.mkdir(parents=True, exist_ok=True)
        EA_RAW_DUMP.write_text(
            json.dumps({"items": raw_items, "filtered": deduped}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote raw dump to {EA_RAW_DUMP}.", flush=True)

    empty_exit = refuse_empty_result(
        deduped,
        label="EA library",
        allow_empty=args.allow_empty,
        output_path=GAMES_EA_JSON,
    )
    if empty_exit is not None:
        stats.error(
            "No EA games returned. Confirm you own PC titles on EA App, then reconnect on Connections."
        )
        return stats.finish("fetch_ea", t0, exit_code=empty_exit)

    slugs = []
    for item in deduped:
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        slug = product.get("gameSlug")
        if isinstance(slug, str) and slug:
            slugs.append(slug)
    play_by_slug: dict[str, dict] = {}
    try:
        play_rows = run_with_heartbeat(
            lambda: client.get_play_times(sorted(set(slugs))),
            "EA play times",
        )
        for pt in play_rows:
            s = pt.get("gameSlug")
            if isinstance(s, str):
                play_by_slug[s] = pt
    except Exception as e:
        print(f"  Play-time warning: {e}", flush=True)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []
    def _sort_key(row: dict) -> str:
        return _clean_name(str((row.get("product") or {}).get("name") or ""))

    for i, item in enumerate(sorted(deduped, key=_sort_key), 1):
        name = _clean_name(str((item.get("product") or {}).get("name") or ""))
        print(f"[{i}/{len(deduped)}] {name}", flush=True)
        cached = existing.get(_row_id(item))
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}", flush=True)
        row = _build_row(item, hltb=hltb, play_by_slug=play_by_slug)
        games_out.append(
            merge_cached_row(row, cached, authoritative=EA, hltb_updated=hltb_updated)
        )

    drift_exit = refuse_drift_result(
        games_out,
        label="EA library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_EA_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_ea", t0, exit_code=drift_exit)

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=row_key_by_id,
        no_carry=args.no_carry,
    )

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "ea",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_EA_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_EA_JSON}.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_ea", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
