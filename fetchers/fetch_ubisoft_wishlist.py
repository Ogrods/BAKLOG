#!/usr/bin/env python3
"""Fetch Ubisoft Store wishlist into games_wishlist_ubisoft.json.

The Ubisoft Connect API tokens used by ``fetch_ubisoft.py`` only cover the
library on ``public-ubiservices.ubi.com`` — the storefront on
``store.ubisoft.com`` (Salesforce Commerce Cloud / Demandware) is a separate
auth context with its own ``dwsid`` session cookie. The wishlist page is
*server-rendered*: there is no JSON API call to scrape, the items are baked
into the HTML response.

We piggyback on the same Chrome/Edge profile the Connections page already uses
to sign in to Ubisoft (``cache/auth/profiles/ubisoft``). One headless page
load with that profile yields a fully populated wishlist HTML; we parse the
``product-tile  wishlist-product-tile`` tiles plus the companion
``var product = {...};`` blob each tile renders and emit rows in the shared
dashboard wishlist schema (``store: "wishlist"``, ``wishlist_store: "ubisoft"``).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid
from auth.secrets import profile_dir
from clients.hltb_client import HltbClient
from fetchers._base import (
    add_allow_empty_arg,
    add_only_new_arg,
    catalog_file,
    configure_stdout,
    refuse_drift_result,
    refuse_empty_result,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from shared.money import format_price, normalize_currency_code

GAMES_UBISOFT_WISHLIST_JSON = Path("games_wishlist_ubisoft.json")
WISHLIST_URL = "https://store.ubisoft.com/us/wishlist/?lang=en_US"
HLTB_DELAY_SEC = 1.0

# Outer wishlist tile. The literal class string uses two spaces between
# "card" and "wishlist-product-tile" (Demandware quirk) but we tolerate any
# whitespace. The inner button-wrappers also carry ``wishlist-product-tile``
# but never ``product-tile`` — match both to pick only the outer card.
_TILE_OPEN_RE = re.compile(
    r'<div\b[^>]*\bclass="[^"]*\bproduct-tile\b[^"]*\bwishlist-product-tile\b[^"]*"[^>]*>',
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r'\bdata-([a-z][a-z0-9-]*)="([^"]*)"', re.IGNORECASE)

# The Demandware template emits one ``var product = {...};`` JSON blob per
# tile, all on a single line, so a non-greedy match against ``};`` is safe.
_PRODUCT_BLOB_RE = re.compile(r"var\s+product\s*=\s*(\{[^\n]+?\})\s*;", re.MULTILINE)

# Pretty-name sources (in order of preference). Each operates on a slice of
# HTML starting at the tile's opening ``<div>`` tag.
_TITLE_GO_TO_RE = re.compile(r'title="Go to product:\s*([^"]+)"', re.IGNORECASE)
_IMG_ALT_RE = re.compile(r'<img[^>]*\bclass="[^"]*\bproduct_image\b[^"]*"[^>]*\balt="([^"]+)"', re.IGNORECASE)
# data-tc100 attr is HTML-entity-encoded JSON; we just need the productName.
_TC100_NAME_RE = re.compile(r'data-tc100="[^"]*&quot;productName&quot;:&quot;([^"&]+)&quot;', re.IGNORECASE)

# Empty wishlist / signed-out heuristics
_EMPTY_PHRASE = re.compile(
    r"Log in to access your wishlist|Your wishlist is empty|Looking for new games to add",
    re.IGNORECASE,
)

# Things on the storefront that are technically "tiles" but not base games we
# want to track as wishlistable backlog candidates. We accept anything whose
# edition word ends in "Edition" or matches a known base-game suffix.
_GAME_EDITION_RE = re.compile(
    r"\b(edition|standard|resynced|definitive|anniversary|remaster|remastered|"
    r"reckoning|year\s*\d+|gold|deluxe|ultimate|elite|premium|complete)\b",
    re.IGNORECASE,
)


@dataclass
class WishlistItem:
    store_id: str            # data-itemid (also product.id)
    mdm_id: str | None       # data-mdmiid – maps to library MDM ids
    brand: str | None        # franchise (e.g. Assassin's Creed)
    name: str                # human-readable title
    edition: str | None
    genre_text: str | None
    image_url: str | None
    store_url: str
    currency: str | None
    unit_price: float | None
    unit_sale_price: float | None
    platform: str | None
    kind: str                # "game" or "dlc"


def _wishlist_page_ready(html: str) -> bool:
    """True when wishlist tiles are in the DOM or the page shows an empty list."""
    if _TILE_OPEN_RE.search(html):
        return True
    # Hydrated wishlist shell: list container is present and the page is fully sized.
    if (
        "wishlist-items-list" in html
        and len(html) > 200_000
        and _EMPTY_PHRASE.search(html)
    ):
        return True
    return False


def _fetch_wishlist_html(timeout_s: int = 45) -> tuple[str, str]:
    """Load the wishlist page with the saved Ubisoft profile, headless."""
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir("ubisoft")
    if not profile.exists():
        raise RuntimeError(
            "No saved Ubisoft profile at cache/auth/profiles/ubisoft. "
            "Open the Connections page and connect Ubisoft first."
        )

    poll_deadline_s = min(max(timeout_s - 5, 15), 25)
    poll_interval_ms = 500

    with launch_persistent_profile(str(profile), headless=True) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)

        title = ""
        html = ""
        deadline = time.time() + poll_deadline_s
        while time.time() < deadline:
            title = page.title() or ""
            html = page.content()
            if _wishlist_page_ready(html):
                break
            if "sign in" in title.lower():
                break
            page.wait_for_timeout(poll_interval_ms)

        return title, html


def _classify_kind(name: str, edition: str | None) -> str:
    """Best-effort split between base games and DLC/cosmetics/currency packs.

    We err on the side of *keeping* items unless the edition looks like a
    pack/skin/currency bundle — base-game editions consistently end in
    ``Edition`` (Standard/Deluxe/Gold/Ultimate/Elite/Anniversary/etc) or have
    a known suffix like ``Resynced`` / ``Definitive``.
    """
    edition_s = (edition or "").strip()
    name_s = (name or "")

    if edition_s and _GAME_EDITION_RE.search(edition_s):
        return "game"

    dlc_signals = (
        "pack", "skin", "bundle", "currency", "credits", "charm",
        "emblem", "booster", "season pass", "year pass",
    )
    if edition_s and any(tok in edition_s.lower() for tok in dlc_signals):
        return "dlc"
    dlc_name_tokens = (" DLC ", "-DLC", "WEAPON SKIN", "MASK PACK", "PREMIER PACK", "WELCOME PACK")
    if any(tok.upper() in name_s.upper() for tok in dlc_name_tokens):
        return "dlc"

    return "game" if edition_s else "dlc"


def _parse_tiles(html: str) -> list[WishlistItem]:
    """Parse outer wishlist tiles and pair them with their product JSON blob."""
    blobs: dict[str, dict] = {}
    for raw in _PRODUCT_BLOB_RE.findall(html):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        pid = str(obj.get("id") or "").strip()
        if pid:
            blobs[pid] = obj

    items: list[WishlistItem] = []
    for match in _TILE_OPEN_RE.finditer(html):
        tag = match.group(0)
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        item_id = attrs.get("itemid")
        if not item_id:
            continue
        product = blobs.get(item_id, {})

        # Pretty-name pass: the title attribute on the thumb link, the img
        # alt, and the data-tc100 ``productName`` are all camel-cased and free
        # of the all-caps "-WW"/"-NCSA" SKU suffix that ``product.name`` has.
        tile_body = html[match.end(): match.end() + 6000]
        name = ""
        for pat in (_TITLE_GO_TO_RE, _IMG_ALT_RE, _TC100_NAME_RE):
            m = pat.search(tile_body)
            if m:
                name = m.group(1).strip()
                if name:
                    break
        if not name:
            raw = (product.get("name") or "").strip()
            name = re.sub(r"\s*[-–]\s*(WW|NCSA|W|EU|US|EMEA)\s*$", "", raw, flags=re.IGNORECASE)
            name = " ".join(piece.capitalize() if piece.isupper() else piece for piece in name.split())
        if not name:
            name = item_id

        edition = (product.get("edition") or "").strip() or None
        kind = _classify_kind(name, edition)
        items.append(
            WishlistItem(
                store_id=item_id,
                mdm_id=(attrs.get("mdmiid") or None),
                brand=attrs.get("brand") or product.get("brand") or None,
                name=name,
                edition=edition,
                genre_text=(product.get("genre") or None),
                image_url=product.get("image_url") or None,
                store_url=product.get("url")
                    or f"https://store.ubisoft.com/us/{item_id}.html?lang=en_US",
                currency=product.get("currency"),
                unit_price=product.get("unit_price"),
                unit_sale_price=product.get("unit_sale_price"),
                platform=product.get("platform") or None,
                kind=kind,
            )
        )
    return items


def _fmt_price(value: float | None, currency: str | None) -> str | None:
    if value is None or currency is None:
        return None
    if value == 0:
        return "Free"
    return format_price(value, normalize_currency_code(currency))


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
    tags: list[str] = []
    if item.brand:
        tags.append(item.brand)
    if item.kind != "game":
        tags.append(item.kind.upper())

    genres: list[str] = []
    if item.genre_text:
        for piece in re.split(r"[,/]", item.genre_text):
            label = piece.strip()
            if label:
                genres.append(label)

    discount_pct = None
    if (
        item.unit_price is not None
        and item.unit_sale_price is not None
        and item.unit_price > 0
        and item.unit_sale_price < item.unit_price
    ):
        discount_pct = round(100 * (1 - item.unit_sale_price / item.unit_price))

    price = _fmt_price(item.unit_sale_price, item.currency)
    price_initial = _fmt_price(item.unit_price, item.currency)

    return {
        "store": "wishlist",
        "wishlist_store": "ubisoft",
        "id": f"ubisoft-{item.store_id}",
        "ubisoft_product_id": item.store_id,
        "ubisoft_mdm_id": item.mdm_id,
        "ubisoft_kind": item.kind,
        "name": item.name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": None,
        "genres": list(dict.fromkeys(genres)),
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
        "price": price,
        "price_initial": price_initial,
        "discount_percent": discount_pct,
        "currency": item.currency,
        "edition": item.edition,
    }


def _load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_UBISOFT_WISHLIST_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_UBISOFT_WISHLIST_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Ubisoft Store wishlist into games_wishlist_ubisoft.json",
    )
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    add_only_new_arg(parser)
    parser.add_argument(
        "--include-dlc",
        action="store_true",
        help="Also write DLC/cosmetic/currency tiles (default keeps only base games)",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_ubisoft_wishlist")
    stats = RunStats()

    load_dotenv()
    print("Fetching Ubisoft wishlist via headless storefront page...", flush=True)

    try:
        title, html = run_with_heartbeat(_fetch_wishlist_html, "Ubisoft wishlist capture")
    except Exception as exc:
        mark_invalid("ubisoft", error=f"wishlist page fetch failed: {exc}")
        stats.error(str(exc))
        return stats.finish("fetch_ubisoft_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if "Sign in" in title or _EMPTY_PHRASE.search(html or "") and "<div" not in (html or ""):
        msg = (
            "Ubisoft storefront session is missing or expired. Open the "
            "Connections page, click Ubisoft \u2192 Connect, and sign in to "
            "store.ubisoft.com inside the launched browser window."
        )
        mark_invalid("ubisoft", error=msg)
        stats.error(msg)
        return stats.finish("fetch_ubisoft_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    parsed = _parse_tiles(html)
    print(f"  parsed {len(parsed)} wishlist tiles (kept all kinds)", flush=True)

    if args.include_dlc:
        kept = list(parsed)
        dropped: list[WishlistItem] = []
    else:
        kept = [item for item in parsed if item.kind == "game"]
        dropped = [item for item in parsed if item.kind != "game"]
    if dropped:
        print(
            f"  filtered {len(dropped)} non-game tiles (DLC/skins/currency); "
            f"pass --include-dlc to keep them",
            flush=True,
        )

    empty_exit = refuse_empty_result(
        kept,
        label="Ubisoft wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_UBISOFT_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_ubisoft_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        kept,
        label="Ubisoft wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_UBISOFT_WISHLIST_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_ubisoft_wishlist", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []

    for i, item in enumerate(kept, 1):
        row_id = f"ubisoft-{item.store_id}"
        cached = existing.get(row_id)
        if args.only_new and cached:
            rows.append(cached)
            continue
        print(f"[{i}/{len(kept)}] {item.name}", flush=True)
        hltb = None
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
                except Exception as exc:
                    print(f"  HLTB warning: {exc}", flush=True)
        rows.append(_build_row(item, hltb))

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "wishlist_ubisoft",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    write_catalog_text(GAMES_UBISOFT_WISHLIST_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(
        f"\nWrote {len(rows)} games to {GAMES_UBISOFT_WISHLIST_JSON}.",
        flush=True,
    )
    print("Reload the dashboard to see Ubisoft items in the Wishlist tab.", flush=True)
    stats.ok = len(rows)
    return stats.finish(
        "fetch_ubisoft_wishlist", t0, exit_code=0, extra=f"{len(rows)} games"
    )


if __name__ == "__main__":
    raise SystemExit(main())
