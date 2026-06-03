#!/usr/bin/env python3
"""Fetch Epic Games Store wishlist into games_wishlist_epic.json.

Uses the storefront session cookie (``EPIC_STORE_COOKIE`` in ``.env``) — the
launcher OAuth that ``fetch_epic.py`` uses can't reach the wishlist endpoint
because it sits behind a separate storefront auth context. See README for how
to grab the cookie from DevTools.

Output rows match the shared dashboard wishlist schema (``store: "wishlist"``,
``wishlist_store: "epic"``) so the merged Wishlist tab + deal radar pick them
up alongside Steam and GOG entries.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from epic_client import EpicAuthError, EpicStoreClient
from auth import mark_invalid, resolve_env
from fetchers._base import add_allow_empty_arg, refuse_drift_result, refuse_empty_result
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient

GAMES_WISHLIST_EPIC_JSON = Path("games_wishlist_epic.json")
HLTB_DELAY_SEC = 1.0

LIBRARY_IMAGE_TYPES = (
    "DieselGameBoxTall",
    "Thumbnail",
    "OfferImageTall",
    "VaultClosed",
    "DieselGameBox",
)
HEADER_IMAGE_TYPES = (
    "OfferImageWide",
    "DieselStoreFrontWide",
    "DieselGameBox",
    "Featured",
)


def _epic_auth_hint(exc: EpicAuthError) -> str:
    msg = str(exc)
    if "notLoggedIn" in msg:
        return (
            "Epic storefront session expired or never captured. On Connections, "
            "use Epic (wishlist) → Connect, sign in at store.epicgames.com/wishlist, "
            "and wait until your wishlist finishes loading."
        )
    return msg


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _pick_image(key_images: list | None, types: tuple[str, ...]) -> str | None:
    if not key_images:
        return None
    by_type = {k.get("type"): k.get("url") for k in key_images if isinstance(k, dict)}
    for t in types:
        url = by_type.get(t)
        if url:
            return url
    return None


def _is_public_slug(value: str | None) -> bool:
    if not value:
        return False
    s = str(value).strip()
    return bool(s) and s.replace("-", "").replace("_", "").isalnum() and s == s.lower()


def _store_url(offer: dict | None, fallback_name: str) -> str:
    if offer:
        for key in ("productSlug", "urlSlug", "pageSlug"):
            slug = offer.get(key)
            if _is_public_slug(slug):
                return f"https://store.epicgames.com/en-US/p/{str(slug).strip()}"
    return f"https://store.epicgames.com/en-US/browse?q={quote(fallback_name)}"


def _genres(offer: dict | None) -> list[str]:
    """Pull human-readable category names from Epic tags."""
    if not offer:
        return []
    out: list[str] = []
    for tag in offer.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        name = tag.get("name") or tag.get("id")
        if name:
            out.append(str(name))
    return list(dict.fromkeys(out))


def _price_fields(offer: dict | None) -> dict:
    """Return price/price_initial/discount_percent/currency from an Epic offer."""
    blank = {
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }
    if not offer:
        return blank
    price = (offer.get("price") or {}).get("totalPrice") or {}
    if not price:
        return blank
    currency = price.get("currencyCode")
    final_cents = price.get("discountPrice")
    base_cents = price.get("originalPrice")
    fmt = price.get("fmtPrice") or {}
    discount_pct = None
    if isinstance(base_cents, (int, float)) and base_cents > 0 and isinstance(final_cents, (int, float)):
        discount_pct = round(100 * (1 - final_cents / base_cents))
    price_str = fmt.get("discountPrice") or fmt.get("originalPrice")
    price_initial_str = fmt.get("originalPrice")
    if final_cents == 0 and not price_str:
        price_str = "Free"
    return {
        "price": price_str,
        "price_initial": price_initial_str,
        "discount_percent": discount_pct,
        "currency": currency,
    }


def _release(offer: dict | None) -> str | None:
    if not offer:
        return None
    for key in ("releaseDate", "pcReleaseDate", "effectiveDate"):
        v = offer.get(key)
        if v:
            return v
    return None


def _build_row(element: dict, hltb: dict | None) -> dict | None:
    offer = element.get("offer") or {}
    namespace = element.get("namespace") or offer.get("namespace")
    offer_id = element.get("offerId") or offer.get("id")
    if not namespace or not offer_id:
        return None
    name = offer.get("title") or str(offer_id)
    key_images = offer.get("keyImages") or []
    header = _pick_image(key_images, HEADER_IMAGE_TYPES)
    library = _pick_image(key_images, LIBRARY_IMAGE_TYPES) or header
    price_info = _price_fields(offer)

    row = {
        "store": "wishlist",
        "wishlist_store": "epic",
        "id": f"epic-{namespace}:{offer_id}",
        "epic_namespace": namespace,
        "epic_offer_id": offer_id,
        "name": name,
        "wishlist_added": element.get("created"),
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": header,
        "library_image": library,
        "release_date": _release(offer),
        "genres": _genres(offer),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": (hltb or {}).get("hltb_main_hours"),
        "hltb_main_extra_hours": (hltb or {}).get("hltb_main_extra_hours"),
        "hltb_completionist_hours": (hltb or {}).get("hltb_completionist_hours"),
        "hltb_match_confidence": (hltb or {}).get("hltb_match_confidence"),
        "hltb_name": (hltb or {}).get("hltb_name"),
        "store_url": _store_url(offer, name),
        "type": "game",
    }
    row.update(price_info)
    return row


def _load_existing() -> dict[str, dict]:
    if not GAMES_WISHLIST_EPIC_JSON.exists():
        return {}
    try:
        data = json.loads(GAMES_WISHLIST_EPIC_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic wishlist into games_wishlist_epic.json")
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slower)")
    parser.add_argument("--country", default="US", help="Storefront country code (default US)")
    parser.add_argument("--locale", default="en-US", help="Storefront locale (default en-US)")
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_epic_wishlist")
    stats = RunStats()

    load_dotenv()
    cookie = resolve_env("EPIC_STORE_COOKIE", provider="epic_wishlist")
    if not cookie:
        print(
            "EPIC_STORE_COOKIE is not set.\n\n"
            "On Connections, use Epic (wishlist) → Connect, sign in at "
            "store.epicgames.com/wishlist, clear any Cloudflare check, and "
            "wait until your wishlist finishes loading.\n",
            file=sys.stderr,
        )
        return stats.finish("fetch_epic_wishlist", t0, exit_code=1)

    try:
        client = EpicStoreClient(cookie=cookie)
    except EpicAuthError as e:
        hint = _epic_auth_hint(e)
        mark_invalid("epic_wishlist", error=hint)
        stats.error(hint)
        return stats.finish("fetch_epic_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    print("Fetching Epic wishlist via storefront GraphQL...", flush=True)
    try:
        elements = client.get_wishlist(country=args.country, locale=args.locale)
    except EpicAuthError as e:
        hint = _epic_auth_hint(e)
        mark_invalid("epic_wishlist", error=hint)
        stats.error(hint)
        return stats.finish("fetch_epic_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    print(f"  {len(elements)} wishlist items", flush=True)

    empty_exit = refuse_empty_result(
        elements,
        label="Epic wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_WISHLIST_EPIC_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_epic_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        elements,
        label="Epic wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_WISHLIST_EPIC_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_epic_wishlist", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []

    for i, el in enumerate(elements, 1):
        offer = el.get("offer") or {}
        name = offer.get("title") or el.get("offerId") or "?"
        print(f"[{i}/{len(elements)}] {name}")

        hltb = None
        row_id = f"epic-{el.get('namespace') or offer.get('namespace')}:{el.get('offerId') or offer.get('id')}"
        cached = existing.get(row_id)
        if hltb_client and name:
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
                    hltb = hltb_client.lookup(name)
                except Exception as e:
                    print(f"  HLTB warning: {e}")

        row = _build_row(el, hltb)
        if row is None:
            continue
        rows.append(row)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "wishlist_epic",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    GAMES_WISHLIST_EPIC_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(rows)} games to {GAMES_WISHLIST_EPIC_JSON}.", flush=True)
    print("Reload the dashboard to see Epic items in the Wishlist tab.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_epic_wishlist", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    raise SystemExit(main())
