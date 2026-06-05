#!/usr/bin/env python3
"""Fetch Epic Games Store wishlist into games_wishlist_epic.json.

Uses the saved Epic Store browser profile (Connections -> Epic wishlist) and
loads store.epicgames.com/wishlist headlessly, capturing storefront GraphQL
responses. No cookie replay from Python (Cloudflare binds cf_clearance to the
browser TLS fingerprint).

Output rows match the shared dashboard wishlist schema (``store: "wishlist"``,
``wishlist_store: "epic"``).
"""

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

from auth import mark_invalid
from auth.epic_wishlist_session import (
    cloudflare_interstitial,
    enrich_wishlist_elements_with_catalog,
    extract_wishlist_payloads_from_html,
    graphql_debug_entry,
    is_epic_graphql_url,
    storefront_auth_blocked,
    storefront_auth_error_message,
    storefront_signed_out,
    wishlist_capture_complete_from_html,
    wishlist_graphql_ok,
)
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

GAMES_WISHLIST_EPIC_JSON = Path("games_wishlist_epic.json")
WISHLIST_URL = "https://store.epicgames.com/en-US/wishlist"
def dump_dir() -> Path:
    from shared.profile_paths import epic_cache_dir

    return epic_cache_dir()


def dump_html() -> Path:
    return dump_dir() / "wishlist_dump.html"


def dump_json() -> Path:
    return dump_dir() / "wishlist_dump.json"
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


def _elements_from_payload(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or payload
    if not isinstance(data, dict):
        return []
    wishlist = data.get("Wishlist")
    if not isinstance(wishlist, dict):
        return []
    items = wishlist.get("wishlistItems")
    if not isinstance(items, dict):
        return []
    elements = items.get("elements")
    if not isinstance(elements, list):
        return []
    return [el for el in elements if isinstance(el, dict)]


def parse_wishlist_sources(html: str, api_payloads: list[Any]) -> list[dict]:
    """Merge wishlist elements from captured GraphQL and dehydrated HTML state."""
    all_payloads = list(api_payloads)
    all_payloads.extend(extract_wishlist_payloads_from_html(html))
    found: dict[str, dict] = {}
    for payload in all_payloads:
        for el in _elements_from_payload(payload):
            offer = el.get("offer") or {}
            namespace = el.get("namespace") or offer.get("namespace")
            offer_id = el.get("offerId") or offer.get("id")
            eid = el.get("id") or (f"{namespace}:{offer_id}" if namespace and offer_id else None)
            if not eid:
                continue
            found.setdefault(str(eid), el)
    return enrich_wishlist_elements_with_catalog(html, list(found.values()))


def _wishlist_capture_complete(html: str, api_payloads: list[Any]) -> bool:
    if any(wishlist_graphql_ok(p) for p in api_payloads):
        return True
    return wishlist_capture_complete_from_html(html)


def _drain_wishlist_candidates(
    candidates: list[Any], seen: list[dict[str, Any]] | None = None
) -> list[Any]:
    """Parse stashed GraphQL responses on the main thread (safe for CDP)."""
    found: list[Any] = []
    while candidates:
        resp = candidates.pop(0)
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            continue
        if seen is not None:
            try:
                seen.append(graphql_debug_entry(resp.url or "", payload))
            except Exception:  # noqa: BLE001
                pass
        if wishlist_graphql_ok(payload):
            found.append(payload)
    return found


def _fetch_with_profile(*, dump: bool = False, timeout_s: int = 45) -> tuple[str, str, list[Any]]:
    from auth.cdp_browser import STEALTH_INIT_SCRIPT, launch_persistent_profile

    profile = profile_dir("epic_wishlist")
    if not profile.exists():
        raise RuntimeError(
            "No saved Epic wishlist profile at cache/auth/profiles/epic_wishlist. "
            "Open the Connections page and connect 'Epic (wishlist)' first."
        )

    api_payloads: list[Any] = []
    seen_graphql: list[dict[str, Any]] = []
    # Network handlers run on the CDP reader thread; calling response.json()
    # there deadlocks (getResponseBody waits on the same thread). Stash
    # candidate responses and read their bodies from the main thread below.
    candidates: list[Any] = []

    def _capture(response) -> None:
        try:
            if not is_epic_graphql_url(response.url or ""):
                return
            if response.status == 200:
                candidates.append(response)
        except Exception:  # noqa: BLE001
            pass

    poll_deadline_s = min(max(timeout_s - 5, 20), 25)
    poll_interval_ms = 500

    # Match the headed connect window (--start-maximized, no off-screen offset).
    # cf_clearance is bound to the browser fingerprint; off-screen positioning can
    # still trigger a fresh Cloudflare Turnstile that never auto-resolves headlessly.
    with launch_persistent_profile(str(profile), headless=False) as ctx:
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", _capture)
        page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)

        deadline = time.time() + poll_deadline_s
        while time.time() < deadline:
            new_payloads = _drain_wishlist_candidates(candidates, seen_graphql)
            if new_payloads:
                api_payloads.extend(new_payloads)
                break
            html = page.content()
            url = page.url or WISHLIST_URL
            # Cloudflare may show briefly on wishlist even with a valid profile —
            # keep polling so headed Chrome can auto-resolve before we give up.
            if cloudflare_interstitial(html, url):
                page.wait_for_timeout(poll_interval_ms)
                continue
            if storefront_signed_out(html, url):
                break
            page.wait_for_timeout(poll_interval_ms)

        if not api_payloads:
            api_payloads.extend(_drain_wishlist_candidates(candidates, seen_graphql))

        html = page.content()
        url = page.url or WISHLIST_URL

        if dump:
            dump_dir().mkdir(parents=True, exist_ok=True)
            dump_html().write_text(html, encoding="utf-8")
            dump_json().write_text(
                json.dumps(
                    {
                        "url": url,
                        "api_payload_count": len(api_payloads),
                        "api_payloads": api_payloads[:20],
                        "graphql_seen": seen_graphql[:50],
                        "element_count": len(parse_wishlist_sources(html, api_payloads)),
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"  wrote {dump_html()} and {dump_json()}", flush=True)

        return html, url, api_payloads


def _load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_WISHLIST_EPIC_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_WISHLIST_EPIC_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic wishlist into games_wishlist_epic.json")
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    parser.add_argument("--country", default="US", help="Storefront country code (default US)")
    parser.add_argument("--locale", default="en-US", help="Storefront locale (default en-US)")
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save raw HTML + captured GraphQL to {dump_dir()}/",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_epic_wishlist")
    stats = RunStats()
    load_dotenv()

    print("Fetching Epic wishlist via saved storefront profile...", flush=True)
    try:
        html, url, api_payloads = run_with_heartbeat(
            lambda: _fetch_with_profile(dump=args.dump),
            "Epic wishlist capture",
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        is_transport = any(
            tok in msg.lower()
            for tok in ("cdp command timed out", "websocket", "browser", "debugging endpoint")
        )
        if is_transport:
            stats.error(f"wishlist fetch transport error: {msg}")
            return stats.finish("fetch_epic_wishlist", t0, exit_code=1)
        mark_invalid("epic_wishlist", error=f"wishlist fetch failed: {msg}")
        stats.error(msg)
        return stats.finish("fetch_epic_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if not _wishlist_capture_complete(html, api_payloads) and storefront_auth_blocked(html, url):
        msg = storefront_auth_error_message(html, url)
        mark_invalid("epic_wishlist", error=msg)
        stats.error(msg)
        return stats.finish("fetch_epic_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    elements = parse_wishlist_sources(html, api_payloads)
    print(
        f"  parsed {len(elements)} wishlist items ({len(api_payloads)} captured GraphQL responses)",
        flush=True,
    )

    if args.dump:
        return stats.finish("fetch_epic_wishlist", t0, exit_code=0, extra="dump only")

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
        print(f"[{i}/{len(elements)}] {name}", flush=True)

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
                except Exception as exc:  # noqa: BLE001
                    print(f"  HLTB warning: {exc}", flush=True)

        row = _build_row(el, hltb)
        if row is None:
            continue
        rows.append(row)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "wishlist_epic",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    write_catalog_text(GAMES_WISHLIST_EPIC_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(rows)} games to {GAMES_WISHLIST_EPIC_JSON}.", flush=True)
    print("Reload the dashboard to see Epic items in the Wishlist tab.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_epic_wishlist", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    raise SystemExit(main())
