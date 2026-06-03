#!/usr/bin/env python3
"""Fetch EA App library via Juno GraphQL (unofficial)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid
from auth.secrets import profile_dir
from ea_client import (
    EA_PLAY_OWNERSHIP,
    REAL_OWNERSHIP,
    XGP_ONLY,
    EaAuthError,
    EaClient,
)
from fetchers._authoritative import EA
from fetchers._base import add_allow_empty_arg, merge_cached_row, refuse_drift_result, catalog_file, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient

GAMES_EA_JSON = Path("games_ea.json")
def raw_dump_json() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "ea_raw.json"

HLTB_DELAY_SEC = 1.0
EA_GRAPHQL_HOST = "service-aggregation-layer.juno.ea.com"
# A logged-in ea.com page that reliably fires an authenticated SAL GraphQL call,
# so we can sniff the user's own web-session Bearer token from the request.
EA_TRIGGER_URL = "https://www.ea.com/sales/deals"

_TM_CHARS = "".maketrans({"®": "", "™": "", "©": ""})


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").translate(_TM_CHARS).split()).strip()


def _sniff_session(*, timeout_s: int = 45) -> tuple[str, list[dict]]:
    """Replay the user's saved ea.com login to capture their own Bearer token.

    Launches the persistent EA profile headlessly, opens a logged-in ea.com page
    that fires an authenticated GraphQL request, and reads the Authorization
    header off that request — the same token the website obtained for the user.
    """
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir("ea")
    if not profile.exists():
        raise EaAuthError(
            "No saved EA profile at cache/auth/profiles/ea. "
            "Open the Connections page and connect EA App first."
        )

    captured: dict[str, str] = {}

    def on_request(request) -> None:
        if EA_GRAPHQL_HOST not in (request.url or "").lower():
            return
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth:
            return
        token = auth.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token:
            captured["token"] = token

    with launch_persistent_profile(str(profile), headless=True) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", on_request)
        try:
            page.goto(EA_TRIGGER_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + timeout_s
        while time.time() < deadline and "token" not in captured:
            page.wait_for_timeout(500)
        cookies = ctx.cookies()

    token = captured.get("token")
    if not token:
        raise EaAuthError(
            "Could not capture an EA web-session token — your EA login may have expired. "
            "Reconnect EA App on the Connections page."
        )
    return token, cookies


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
        # Drop demos/tools when EA labels them explicitly.
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
        tags.append("xbox_game_pass")
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
    parser.add_argument("--skip-hltb", action="store_true")
    parser.add_argument("--dump-raw", action="store_true")
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_ea")
    stats = RunStats()

    try:
        token, cookies = _sniff_session()
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
        raw_dump_json().parent.mkdir(parents=True, exist_ok=True)
        raw_dump_json().write_text(
            json.dumps({"items": raw_items, "filtered": deduped}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote raw dump to {raw_dump_json()}.", flush=True)

    if not deduped:
        stats.error(
            "No EA games returned. Confirm you own PC titles on EA App, then reconnect on Connections."
        )
        return stats.finish("fetch_ea", t0, exit_code=2)

    slugs = []
    for item in deduped:
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        slug = product.get("gameSlug")
        if isinstance(slug, str) and slug:
            slugs.append(slug)
    play_by_slug: dict[str, dict] = {}
    try:
        for pt in client.get_play_times(sorted(set(slugs))):
            s = pt.get("gameSlug")
            if isinstance(s, str):
                play_by_slug[s] = pt
    except Exception as e:
        print(f"  Play-time warning: {e}", flush=True)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []
    for i, item in enumerate(sorted(deduped, key=lambda x: _clean_name(str((x.get("product") or {}).get("name") or ""))), 1):
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

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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
