#!/usr/bin/env python3
"""Fetch the Xbox Store wishlist into games_wishlist_xbox.json.

The Xbox wishlist isn't surfaced by OpenXBL (its XBL endpoints cover play
history, achievements, friends, etc., but not the storefront wishlist that
lives behind your MSA account on ``xbox.com``). What ``xbox.com/wishlist``
serves is a fully server-rendered React shell with the wishlist data baked
into ``window.__PRELOADED_STATE__``. That global gets consumed + deleted by
React after hydration, so we never see it via JS — we always parse it
straight from the SSR HTML response, which is also what makes this fast and
JS-free for the fetcher (no full browser render required after the request
lands).

Like ``fetch_ubisoft_wishlist.py`` we piggyback on the persistent Chrome/Edge
profile the Connections page already established (``cache/auth/profiles/
xbox_wishlist``). One headless ``context.request.get()`` call to the wishlist
URL with that profile yields the SSR HTML; we carve out
``core2.wishlist.wishlists`` (the canonical wishlist branch) and pair each
wishlist item with its catalog summary from ``core2.products`` (the same SSR
payload hydrates product titles, images, prices, and store URLs in one
shot).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid
from auth.runner import _parse_xbox_preloaded_state
from auth.secrets import profile_dir
from fetchers._base import (
    add_allow_empty_arg,
    catalog_file,
    refuse_drift_result,
    refuse_empty_result,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from hltb_client import HltbClient
from shared.money import format_price, normalize_currency_code

GAMES_XBOX_WISHLIST_JSON = Path("games_wishlist_xbox.json")
WISHLIST_URL = "https://www.xbox.com/en-us/wishlist"
def wishlist_state_dump() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "xbox" / "wishlist_state.json"
HLTB_DELAY_SEC = 1.0

# Microsoft Store product ids ("BigIds") are 10–16-char all-caps alphanumeric
# strings starting with a digit (e.g. "9N16JD2DGTLB", "9NBLGGH4PMVH"). The
# strict pattern avoids matching ISO dates, GUIDs, or title slugs while we
# walk the wishlist subtree for product references.
_BIGID_RE = re.compile(r"[0-9][A-Z0-9]{9,15}")


@dataclass
class WishlistItem:
    product_id: str            # MS Store BigId (e.g. 9N16JD2DGTLB)
    title: str
    image_url: str | None
    store_url: str
    publisher: str | None
    developer: str | None
    genres: list[str]
    release_date: str | None
    price: str | None
    price_initial: str | None
    discount_percent: int | None
    currency: str | None
    added_at: str | None


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
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[7:]
    return u if u.startswith("https://") else None


def _store_url(product_id: str, title: str | None) -> str:
    if product_id:
        # The xbox.com store route accepts ``_/<bigid>`` and resolves the slug.
        return f"https://www.xbox.com/en-us/games/store/_/{product_id}"
    if title:
        return f"https://www.xbox.com/en-us/search/results?q={quote(title)}"
    return "https://www.xbox.com/en-us/games"


def _fetch_wishlist_state(timeout_s: int = 45) -> dict:
    """Headless cookie-authenticated GET with the saved xbox_wishlist profile."""
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir("xbox_wishlist")
    if not profile.exists():
        raise RuntimeError(
            "No saved Xbox wishlist profile at cache/auth/profiles/xbox_wishlist. "
            "Open the Connections page and connect 'Xbox Store wishlist' first."
        )

    with launch_persistent_profile(str(profile), headless=True) as ctx:
        resp = ctx.request.get(WISHLIST_URL, timeout=timeout_s * 1000)
        if resp.status >= 400:
            raise RuntimeError(f"xbox.com/wishlist returned HTTP {resp.status}")
        html = resp.text()
        state = _parse_xbox_preloaded_state(html)
        if not state:
            raise RuntimeError(
                "Could not find __PRELOADED_STATE__ in the xbox.com/wishlist HTML response."
            )
        return state


def _walk(node: Any, depth: int = 0, max_depth: int = 12) -> Iterable[Any]:
    if depth > max_depth or node is None:
        return
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v, depth + 1, max_depth)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, depth + 1, max_depth)


def _extract_wishlist_ids(state: dict) -> tuple[list[tuple[str, str | None]], dict]:
    """Return ``[(product_id, added_at), ...]`` and the raw wishlists branch.

    The Xbox wishlist React store keys items by product BigId. The exact
    container path has shifted historically — sometimes ``wishlists`` is a
    flat list of product ids, sometimes a dict of ``{wishlistId: {items:
    [{productId, addedAt}, ...]}}``. We tolerate both shapes by walking the
    ``core2.wishlist.wishlists`` subtree and collecting any product-id
    fields we find.
    """
    wishlists = ((state.get("core2") or {}).get("wishlist") or {}).get("wishlists") or {}
    found: dict[str, str | None] = {}

    def _pid(value: Any) -> str | None:
        # MS Store BigIds: 12-char uppercase alphanumeric (e.g. 9N16JD2DGTLB).
        # Strict pattern keeps date strings / GUIDs / titles from leaking in.
        if isinstance(value, str) and _BIGID_RE.fullmatch(value):
            return value
        return None

    for node in _walk(wishlists):
        if isinstance(node, dict):
            for key in ("productId", "ProductId", "bigId", "BigId", "id"):
                pid = _pid(node.get(key))
                if pid and pid not in found:
                    found[pid] = (
                        node.get("addedAt")
                        or node.get("AddedAt")
                        or node.get("dateAdded")
                        or node.get("createdDate")
                    )
        elif isinstance(node, str):
            pid = _pid(node)
            if pid and pid not in found:
                found[pid] = None

    return list(found.items()), wishlists


def _index_products(state: dict) -> dict[str, dict]:
    """Build ``{productId: catalog_dict}`` from every catalog branch xbox.com
    ships in the same SSR payload. We scan a few well-known roots first (fast
    path) and then walk the rest of ``core2`` as a fallback for shape drift.
    """
    catalog: dict[str, dict] = {}
    core2 = state.get("core2") or {}

    def _looks_like_product(v: dict) -> bool:
        return any(
            field in v
            for field in ("title", "Title", "displayName", "productTitle", "productSummary")
        ) or "image" in v or "images" in v

    def _ingest(container: Any) -> None:
        if not isinstance(container, dict):
            return
        for k, v in container.items():
            if not isinstance(v, dict) or not _looks_like_product(v):
                continue
            if isinstance(k, str) and _BIGID_RE.fullmatch(k):
                catalog.setdefault(k, v)
            pid = v.get("productId") or v.get("ProductId") or v.get("bigId") or v.get("BigId")
            if isinstance(pid, str) and _BIGID_RE.fullmatch(pid):
                catalog.setdefault(pid, v)

    for root_key in ("products", "productSummaries", "productDetails", "catalog"):
        _ingest(core2.get(root_key))

    for node in _walk(core2, max_depth=10):
        if not isinstance(node, dict):
            continue
        pid = node.get("productId") or node.get("ProductId") or node.get("bigId") or node.get("BigId")
        if isinstance(pid, str) and _BIGID_RE.fullmatch(pid) and pid not in catalog and _looks_like_product(node):
            catalog[pid] = node

    return catalog


def _pick_image(product: dict) -> str | None:
    """Prefer a poster/box-art image; xbox.com ships a few size variants."""
    images = product.get("images") or product.get("Images")
    candidates: list[tuple[int, str]] = []
    if isinstance(images, list):
        for img in images:
            if not isinstance(img, dict):
                continue
            url = img.get("url") or img.get("Url") or img.get("uri")
            purpose = (img.get("purpose") or img.get("imagePurpose") or "").lower()
            width = img.get("width") or img.get("Width") or 0
            try:
                width = int(width)
            except (TypeError, ValueError):
                width = 0
            if not url:
                continue
            # Posters / box art first
            rank = 0
            if "boxart" in purpose or "poster" in purpose:
                rank = 100
            elif "tile" in purpose:
                rank = 50
            elif "logo" in purpose:
                rank = 10
            else:
                rank = 20
            candidates.append((rank * 1000 + min(width, 1000), url))
    if candidates:
        candidates.sort(reverse=True)
        return _https(candidates[0][1])

    # Flat fields seen on some catalog branches
    for key in ("posterImage", "boxArt", "tileImage", "image"):
        url = product.get(key)
        if isinstance(url, str):
            return _https(url)
        if isinstance(url, dict):
            inner = url.get("url") or url.get("Url")
            if inner:
                return _https(inner)
    return None


def _pick_price(product: dict) -> tuple[str | None, str | None, int | None, str | None]:
    price = (
        product.get("specificPrices")
        or product.get("price")
        or product.get("Price")
        or product.get("displaySkuAvailabilities")
    )
    list_price = None
    msrp = None
    currency = None

    def _scan(obj: Any) -> None:
        nonlocal list_price, msrp, currency
        if isinstance(obj, dict):
            lp = obj.get("listPrice") or obj.get("ListPrice")
            mp = obj.get("msrp") or obj.get("MSRP")
            cc = obj.get("currencyCode") or obj.get("CurrencyCode") or obj.get("currency")
            if isinstance(lp, (int, float)) and list_price is None:
                list_price = float(lp)
            if isinstance(mp, (int, float)) and msrp is None:
                msrp = float(mp)
            if isinstance(cc, str) and currency is None:
                currency = cc
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for v in obj:
                _scan(v)

    _scan(price)

    cur_norm = normalize_currency_code(currency)

    def _fmt(v: float | None) -> str | None:
        if v is None:
            return None
        if v == 0:
            return "Free"
        return format_price(v, cur_norm)

    discount = None
    if list_price is not None and msrp is not None and msrp > 0 and list_price < msrp:
        discount = round(100 * (1 - list_price / msrp))

    return _fmt(list_price), _fmt(msrp), discount, cur_norm


def _to_item(product_id: str, added_at: str | None, product: dict | None) -> WishlistItem:
    product = product or {}
    title = (
        product.get("title")
        or product.get("Title")
        or product.get("displayName")
        or product.get("productTitle")
        or product_id
    )
    genres_raw = product.get("categories") or product.get("genres") or product.get("Categories")
    genres: list[str] = []
    if isinstance(genres_raw, list):
        for g in genres_raw:
            if isinstance(g, str) and g.strip():
                genres.append(g.strip())
    release = (
        product.get("releaseDate")
        or product.get("ReleaseDate")
        or product.get("originalReleaseDate")
    )
    if isinstance(release, dict):
        release = release.get("date") or release.get("Date")
    if isinstance(release, str):
        release = release[:10]
    else:
        release = None

    price, price_initial, discount, currency = _pick_price(product)
    return WishlistItem(
        product_id=product_id,
        title=str(title),
        image_url=_pick_image(product),
        store_url=_store_url(product_id, str(title)),
        publisher=product.get("publisherName") or product.get("PublisherName") or None,
        developer=product.get("developerName") or product.get("DeveloperName") or None,
        genres=genres,
        release_date=release,
        price=price,
        price_initial=price_initial,
        discount_percent=discount,
        currency=currency,
        added_at=added_at,
    )


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
    tags: list[str] = []
    if item.publisher:
        tags.append(item.publisher)

    return {
        "store": "wishlist",
        "wishlist_store": "xbox",
        "id": f"xbox-{item.product_id}",
        "xbox_product_id": item.product_id,
        "xbox_added_at": item.added_at,
        "name": item.title,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": item.release_date,
        "genres": list(dict.fromkeys(item.genres)),
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
        "price": item.price,
        "price_initial": item.price_initial,
        "discount_percent": item.discount_percent,
        "currency": item.currency,
        "developer": item.developer,
        "publisher": item.publisher,
    }


def _load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_XBOX_WISHLIST_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_XBOX_WISHLIST_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Xbox Store wishlist into games_wishlist_xbox.json",
    )
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    parser.add_argument(
        "--dump-state",
        action="store_true",
        help=f"Save the raw __PRELOADED_STATE__ wishlist branch to {wishlist_state_dump()}",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_xbox_wishlist")
    stats = RunStats()

    load_dotenv()
    print("Fetching Xbox wishlist via headless xbox.com SSR...", flush=True)

    try:
        state = run_with_heartbeat(_fetch_wishlist_state, "Xbox wishlist capture")
    except Exception as exc:  # noqa: BLE001
        msg = f"wishlist page fetch failed: {exc}"
        mark_invalid("xbox_wishlist", error=msg)
        stats.error(str(exc))
        return stats.finish("fetch_xbox_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    user = state.get("user") or {}
    if not user.get("isSignedIn"):
        msg = (
            "Xbox storefront session is missing or expired. Open the Connections "
            "page, click 'Xbox Store wishlist' \u2192 Reconnect, and sign in to "
            "xbox.com inside the launched browser window."
        )
        mark_invalid("xbox_wishlist", error=msg)
        stats.error(msg)
        return stats.finish("fetch_xbox_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    ids, wishlists_branch = _extract_wishlist_ids(state)
    if args.dump_state or not ids:
        # Dumping the wishlist + sample catalog branch makes shape-drift
        # debugging trivial on a fresh sign-in (or zero-item wishlist).
        wishlist_state_dump().parent.mkdir(parents=True, exist_ok=True)
        wishlist_state_dump().write_text(
            json.dumps(
                {
                    "user": user,
                    "pageMeta": (state.get("pageRequestMetadata") or {}).get("/wishlist"),
                    "wishlists": wishlists_branch,
                    "core2Keys": list((state.get("core2") or {}).keys()),
                },
                indent=2,
                default=str,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if not ids:
            print(f"  wrote raw wishlist branch to {wishlist_state_dump()}", flush=True)
        else:
            print(f"  wrote raw wishlist branch to {wishlist_state_dump()} (--dump-state)", flush=True)

    catalog = _index_products(state)
    items = [_to_item(pid, added_at, catalog.get(pid)) for pid, added_at in ids]
    with_meta = sum(1 for it in items if catalog.get(it.product_id))
    print(f"  parsed {len(items)} wishlist items ({with_meta} with catalog metadata)", flush=True)

    empty_exit = refuse_empty_result(
        items,
        label="Xbox wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_XBOX_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_xbox_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="Xbox wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_XBOX_WISHLIST_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_xbox_wishlist", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []

    for i, item in enumerate(items, 1):
        row_id = f"xbox-{item.product_id}"
        print(f"[{i}/{len(items)}] {item.title}", flush=True)
        hltb = None
        cached = existing.get(row_id)
        if hltb_client and item.title:
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
                    hltb = hltb_client.lookup(item.title)
                except Exception as exc:  # noqa: BLE001
                    print(f"  HLTB warning: {exc}", flush=True)
        rows.append(_build_row(item, hltb))

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "wishlist_xbox",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    write_catalog_text(GAMES_XBOX_WISHLIST_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(
        f"\nWrote {len(rows)} games to {GAMES_XBOX_WISHLIST_JSON}.",
        flush=True,
    )
    stats.ok = len(rows)
    return stats.finish("fetch_xbox_wishlist", t0, exit_code=0)


if __name__ == "__main__":
    sys.exit(main())
