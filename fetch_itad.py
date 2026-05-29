#!/usr/bin/env python3
"""Fetch current prices from IsThereAnyDeal for library + wishlist titles."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from itad_client import ItadClient, ItadError

ITAD_JSON = Path("itad_prices.json")
LIBRARY_FILES = [
    "games_steam.json",
    "games_gog.json",
    "games_psn.json",
    "games_epic.json",
    "games_amazon.json",
]
WISHLIST_FILE = "games_wishlist.json"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _collect_titles() -> list[tuple[str, str]]:
    """(lookup_key, title) — lookup_key is store:id or wishlist:appid."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(key: str, title: str) -> None:
        if not title or key in seen:
            return
        seen.add(key)
        out.append((key, title.strip()))

    for path in LIBRARY_FILES:
        p = Path(path)
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        store = data.get("store") or path.replace("games_", "").replace(".json", "")
        for g in data.get("games", []):
            gid = g.get("id") or g.get("appid")
            if gid is None:
                continue
            add(f"{store}:{gid}", g.get("name") or "")

    wp = Path(WISHLIST_FILE)
    if wp.exists():
        data = json.loads(wp.read_text(encoding="utf-8"))
        for g in data.get("games", []):
            appid = g.get("appid") or g.get("id")
            add(f"wishlist:{appid}", g.get("name") or "")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch ITAD prices into itad_prices.json")
    parser.add_argument("--country", default="US", help="ITAD country code (default US)")
    parser.add_argument("--limit", type=int, default=0, help="Max titles (0 = all)")
    args = parser.parse_args()
    _configure_stdout()
    load_dotenv()
    api_key = os.getenv("ITAD_API_KEY", "").strip()
    if not api_key:
        print("Set ITAD_API_KEY in .env (free key from https://isthereanydeal.com/dev/api/)", file=sys.stderr)
        return 1

    titles = _collect_titles()
    if args.limit:
        titles = titles[: args.limit]
    print(f"Looking up ITAD prices for {len(titles)} titles...")

    try:
        client = ItadClient(api_key, country=args.country)
    except ItadError as e:
        print(str(e), file=sys.stderr)
        return 1

    plain_by_key: dict[str, str] = {}
    for i, (key, title) in enumerate(titles, 1):
        if i % 25 == 0 or i == 1:
            print(f"[{i}/{len(titles)}] {title[:50]}")
        plain = client.lookup_title(title)
        if plain:
            plain_by_key[key] = plain

    print(f"Resolved {len(plain_by_key)} ITAD ids. Fetching prices...")
    plains = list(set(plain_by_key.values()))
    prices_by_plain = client.prices_for_plains(plains)

    by_key: dict[str, dict] = {}
    for key, plain in plain_by_key.items():
        if plain in prices_by_plain:
            by_key[key] = prices_by_plain[plain]

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "country": args.country,
        "count": len(by_key),
        "by_key": by_key,
    }
    ITAD_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(by_key)} price rows to {ITAD_JSON}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
