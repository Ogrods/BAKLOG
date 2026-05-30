#!/usr/bin/env python3
"""Fetch Battle.net library via the unofficial games-and-subs endpoint."""

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

from battlenet_client import BattleNetAuthError, BattleNetClient
from hltb_client import HltbClient

GAMES_BATTLENET_JSON = Path("games_battlenet.json")
RAW_DUMP_JSON = Path("cache/battlenet_raw.json")
HLTB_DELAY_SEC = 1.0

# Map Blizzard's franchise icon filename to the canonical game site.
FRANCHISE_STORE_URLS: dict[str, str] = {
    "world-of-warcraft.svg": "https://worldofwarcraft.blizzard.com/",
    "hearthstone.svg": "https://hearthstone.blizzard.com/",
    "overwatch-2.svg": "https://overwatch.blizzard.com/",
    "overwatch.svg": "https://overwatch.blizzard.com/",
    "diablo-ii-resurrected.svg": "https://diablo2.blizzard.com/",
    "diablo-iii.svg": "https://diablo3.blizzard.com/",
    "diablo-iv.svg": "https://diablo4.blizzard.com/",
    "starcraft-remastered.svg": "https://starcraft.blizzard.com/",
    "starcraft-ii.svg": "https://starcraft2.blizzard.com/",
    "warcraft-rumble.svg": "https://warcraftrumble.blizzard.com/",
    "heroes-of-the-storm.svg": "https://heroesofthestorm.blizzard.com/",
}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# Strip the trademark glyphs Blizzard sprinkles into every title.
_TM_CHARS = "".maketrans({"®": "", "™": "", "©": ""})


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").translate(_TM_CHARS).split()).strip()


def _extract_records(payload: dict) -> list[dict]:
    """Pull the entries we care about from the live response shape."""
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out
    for section in ("gameAccounts", "classicGames", "modernGames", "consoleGames"):
        for item in payload.get(section, []) or []:
            if isinstance(item, dict):
                item = {**item, "_source_section": section}
                out.append(item)
    return out


def _name(item: dict) -> str:
    for k in ("localizedGameName", "title", "displayName", "name"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return _clean_name(v)
    return ""


def _id(item: dict, fallback: str) -> str:
    for k in ("titleId", "productId", "id"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return fallback or "battlenet-unknown"


def _store_url(item: dict, name: str) -> str:
    icon = (item.get("regionalGameFranchiseIconFilename") or "").lower()
    if icon in FRANCHISE_STORE_URLS:
        return FRANCHISE_STORE_URLS[icon]
    return f"https://shop.battle.net/?search={quote(name)}"


def _last_played_iso(item: dict) -> str | None:
    ms = item.get("lastPlayedDateMillis")
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _build_row(item: dict, hltb: dict | None) -> dict:
    name = _name(item) or "Unknown Battle.net title"
    bid = _id(item, name)
    tags: list[str] = []
    if item.get("titleHasGameTime") or item.get("titleHasSubscriptions"):
        tags.append("subscription")
    if (item.get("gameAccountStatus") or "").lower() == "good":
        tags.append("active")
    row = {
        "store": "battlenet",
        "id": bid,
        "battlenet_id": bid,
        "name": name,
        "playtime_minutes": None,
        "last_played": _last_played_iso(item),
        "header_image": None,
        "library_image": None,
        "release_date": None,
        "genres": [],
        "tags": list(dict.fromkeys(tags)),
        "metacritic_score": None,
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
    parser = argparse.ArgumentParser(description="Fetch Battle.net library (unofficial)")
    parser.add_argument("--skip-hltb", action="store_true")
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=f"Also write the raw API response to {RAW_DUMP_JSON} for debugging.",
    )
    args = parser.parse_args()
    _configure_stdout()
    load_dotenv()
    cookie = os.getenv("BATTLENET_COOKIE", "").strip()
    if not cookie:
        print(
            "Set BATTLENET_COOKIE in .env. To get it:\n"
            "  1. Sign in at https://account.battle.net/\n"
            "  2. Visit https://account.battle.net/games\n"
            "  3. DevTools → Network → click the request to /api/games-and-subs\n"
            "  4. Copy the entire 'Cookie' request header value\n"
            "  5. Paste into .env as BATTLENET_COOKIE=<long_cookie_string>",
            file=sys.stderr,
        )
        return 1

    try:
        client = BattleNetClient(cookie)
        raw = client.get_raw_account()
    except BattleNetAuthError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.dump_raw:
        RAW_DUMP_JSON.parent.mkdir(parents=True, exist_ok=True)
        RAW_DUMP_JSON.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote raw response to {RAW_DUMP_JSON}.")

    raw_games = _extract_records(raw)
    seen: dict[str, dict] = {}
    for item in raw_games:
        name = _name(item)
        if not name:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = item
    deduped = list(seen.values())
    print(f"Found {len(deduped)} unique Battle.net entries (from {len(raw_games)} raw).")

    if not deduped:
        print(
            "No game records found in the response. Re-run with --dump-raw and inspect "
            f"{RAW_DUMP_JSON} to confirm the cookie hit the right account.",
            file=sys.stderr,
        )
        return 2

    hltb_client = HltbClient()
    games_out: list[dict] = []
    for i, item in enumerate(deduped, 1):
        name = _name(item)
        print(f"[{i}/{len(deduped)}] {name}")
        hltb = None
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        games_out.append(_build_row(item, hltb))

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "battlenet",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    GAMES_BATTLENET_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(games_out)} games to {GAMES_BATTLENET_JSON}.")
    print("Reload the dashboard to see your Battle.net library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
