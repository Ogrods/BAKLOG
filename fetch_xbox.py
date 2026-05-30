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

from fetchers._base import load_existing_games, merge_cached_row, resolve_hltb_for_row, write_games_json
from hltb_client import HltbClient
from xbox_client import XboxAuthError, XboxClient

GAMES_XBOX_JSON = Path("games_xbox.json")
HLTB_DELAY_SEC = 1.0
XBOX_AUTHORITATIVE = frozenset({
    "store", "id", "xbox_title_id", "name", "playtime_minutes", "last_played",
    "header_image", "library_image", "release_date", "genres", "tags",
    "store_url", "type", "price", "price_initial", "discount_percent", "currency",
    "trophy_progress", "xbox_gamerscore_current", "xbox_gamerscore_total",
})


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
        return "https://" + u[7:]
    return u if u.startswith("https://") else u


def _store_url(title: dict) -> str:
    name = title.get("name") or ""
    tid = title.get("modernTitleId") or title.get("titleId")
    if tid:
        return f"https://www.xbox.com/en-us/games/store/_/{tid}"
    return f"https://www.xbox.com/en-us/search/results?q={quote(name)}"


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
    args = parser.parse_args()
    _configure_stdout()
    load_dotenv()
    api_key = os.getenv("XBL_API_KEY", "").strip()
    if not api_key:
        print("Set XBL_API_KEY in .env (https://xbl.io/)", file=sys.stderr)
        return 1

    try:
        client = XboxClient(api_key)
        gt = client.get_gamertag()
        print(f"OpenXBL account: {gt or '(unknown gamertag)'}")
        titles = client.get_title_history()
    except XboxAuthError as e:
        print(str(e), file=sys.stderr)
        return 1

    games = [t for t in titles if (t.get("type") or "Game").lower() in ("game", "dlc")]
    print(f"Found {len(games)} Xbox titles in title history.")

    hltb_client = HltbClient()
    existing = load_existing_games(GAMES_XBOX_JSON)
    games_out: list[dict] = []

    for i, title in enumerate(games, 1):
        name = title.get("name") or tid_placeholder(title)
        print(f"[{i}/{len(games)}] {name}")
        tid = str(title.get("titleId") or title.get("modernTitleId") or "")
        cached = existing.get(tid) if tid else None
        hltb, hltb_updated = resolve_hltb_for_row(
            skip_hltb=args.skip_hltb,
            only_new=False,
            cached=cached,
            name=name,
            client=hltb_client,
            delay_sec=HLTB_DELAY_SEC,
        )
        row = _build_row(title, hltb)
        games_out.append(
            merge_cached_row(row, cached, authoritative=XBOX_AUTHORITATIVE, hltb_updated=hltb_updated)
        )

    games_out.sort(key=lambda g: g["name"].lower())
    write_games_json(GAMES_XBOX_JSON, store="xbox", games=games_out)
    print(f"\nWrote {len(games_out)} games to {GAMES_XBOX_JSON}.")
    print("Reload the dashboard to see your Xbox library.")
    return 0


def tid_placeholder(title: dict) -> str:
    return str(title.get("titleId") or "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
