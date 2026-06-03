#!/usr/bin/env python3
"""Fetch Xbox / Microsoft Store library via OpenXBL into games_xbox.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from fetchers._authoritative import XBOX
from fetchers._base import (
    add_allow_empty_arg,
    merge_cached_row,
    refuse_drift_result,
    refuse_empty_result,
    catalog_file,
    write_catalog_text,
)
from auth import mark_invalid, resolve_env
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from xbox_client import XboxAuthError, XboxClient

GAMES_XBOX_JSON = Path("games_xbox.json")
HLTB_DELAY_SEC = 1.0


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _https(url: str | None) -> str | None:
    if not url:
        return None
    u = str(url).strip()
    if u.startswith("http://"):
        u = "https://" + u[7:]
    # OpenXBL sometimes returns the non-SSL EDS host; cert is on -ssl variant.
    u = u.replace("://images-eds.xboxlive.com/", "://images-eds-ssl.xboxlive.com/")
    return u if u.startswith("https://") else u


def _store_url(title: dict) -> str:
    name = title.get("name") or ""
    tid = title.get("modernTitleId") or title.get("titleId")
    if tid:
        return f"https://www.xbox.com/en-us/games/store/_/{tid}"
    return f"https://www.xbox.com/en-us/search/results?q={quote(name)}"


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_XBOX_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_XBOX_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(title: dict, hltb: dict | None) -> dict:
    tid = str(title.get("titleId") or title.get("modernTitleId") or "")
    ach = title.get("achievement") or {}
    hist = title.get("titleHistory") or {}
    gp = title.get("gamePass") or {}
    image = _https(title.get("displayImage"))
    tags: list[str] = []
    if gp.get("isGamePass"):
        tags.append("game-pass")
    devices = title.get("devices") or []
    if devices:
        tags.extend(str(d).lower() for d in devices)

    row = {
        "store": "xbox",
        "id": tid,
        "xbox_title_id": tid,
        "name": title.get("name") or "Unknown",
        "playtime_minutes": None,
        "last_played": hist.get("lastTimePlayed"),
        "header_image": image,
        "library_image": image,
        "release_date": None,
        "genres": [],
        "tags": list(dict.fromkeys(tags)),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "trophy_progress": ach.get("progressPercentage"),
        "store_url": _store_url(title),
        "type": (title.get("type") or "game").lower(),
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "xbox_gamerscore_current": ach.get("currentGamerscore"),
        "xbox_gamerscore_total": ach.get("totalGamerscore"),
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
    parser = argparse.ArgumentParser(description="Fetch Xbox library via OpenXBL")
    parser.add_argument("--skip-hltb", action="store_true")
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_xbox")
    stats = RunStats()
    load_dotenv()
    api_key = resolve_env("XBL_API_KEY", provider="xbox")
    if not api_key:
        stats.error("Set XBL_API_KEY in .env (https://xbl.io/)")
        return stats.finish("fetch_xbox", t0, exit_code=1)

    try:
        client = XboxClient(api_key)
        gt = client.get_gamertag()
        print(f"OpenXBL account: {gt or '(unknown gamertag)'}", flush=True)
        titles = client.get_title_history()
    except XboxAuthError as e:
        mark_invalid("xbox", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_xbox", t0, exit_code=EXIT_CODE_AUTH)

    games = [t for t in titles if (t.get("type") or "Game").lower() in ("game", "dlc")]
    print(f"Found {len(games)} Xbox titles in title history.", flush=True)

    empty_exit = refuse_empty_result(
        games,
        label="Xbox library",
        allow_empty=args.allow_empty,
        output_path=GAMES_XBOX_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_xbox", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        games,
        label="Xbox library",
        allow_drift=args.allow_drift,
        output_path=GAMES_XBOX_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_xbox", t0, exit_code=drift_exit)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []

    for i, title in enumerate(games, 1):
        name = title.get("name") or tid_placeholder(title)
        tid = str(title.get("titleId") or title.get("modernTitleId") or "")
        print(f"[{i}/{len(games)}] {name}", flush=True)
        cached = existing.get(tid)
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                stats.warn(f"HLTB for {name!r}: {e}")
        games_out.append(
            merge_cached_row(
                _build_row(title, hltb),
                cached,
                authoritative=XBOX,
                hltb_updated=hltb_updated,
            )
        )
        stats.ok += 1

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "xbox",
        "gamertag": gt,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_XBOX_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_XBOX_JSON}.", flush=True)
    print("Reload the dashboard to see your Xbox library.", flush=True)
    return stats.finish("fetch_xbox", t0, exit_code=0, extra=f"{len(games_out)} games")


def tid_placeholder(title: dict) -> str:
    return str(title.get("titleId") or "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
