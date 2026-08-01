#!/usr/bin/env python3
"""Fetch Humble Store wishlist into games_wishlist_humble.json.

Reuses the saved Humble browser profile (same login as fetch_humble.py).

Humble's /store/wishlist page is a React app that only embeds the wishlist as a
list of product *slugs* in ``window.models.user_json.wishlist`` — no product
details, and the product/lookup API is behind Cloudflare. So we drive a real
(headed, off-screen) Chrome window — same approach as the Epic wishlist fetch —
which clears Cloudflare, read the slug list, then call /store/api/lookup from
inside the page (carrying cf_clearance) to resolve titles, prices and images.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

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

GAMES_HUMBLE_WISHLIST_JSON = Path("games_wishlist_humble.json")
WISHLIST_URL = "https://www.humblebundle.com/store/wishlist"
LOOKUP_PATH = "/store/api/lookup"

# Headed but off-screen: same real-browser fingerprint as the connect window
# (so Cloudflare lets the store API through) without stealing focus.
_WL_WINDOW_POS = (-32000, 0)
_WL_WINDOW_SIZE = (1280, 900)
# How long to wait for Cloudflare to clear and window.models.user_json to appear.
_CLEARANCE_WAIT_SEC = 35
_LOOKUP_BATCH = 20

HLTB_DELAY_SEC = 1.0

# Preferred product image fields from the lookup API (largest first).
_IMAGE_KEYS = (
    "large_capsule",
    "featured_image_recommendation",
    "standard_carousel_image",
    "icon",
)


@dataclass
class WishlistItem:
    product_id: str
    title: str
    image_url: str | None
    store_url: str
    price: str | None
    price_initial: str | None
    discount_percent: int | None
    currency: str | None


def _humble_wishlist_cache() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "humble"


def dump_json() -> Path:
    return _humble_wishlist_cache() / "wishlist_dump.json"


def _price_from_lookup(obj: dict) -> tuple[str | None, str | None, int | None, str | None]:
    cur = obj.get("current_price") if isinstance(obj.get("current_price"), dict) else {}
    full = obj.get("full_price") if isinstance(obj.get("full_price"), dict) else {}
    currency = normalize_currency_code(cur.get("currency") or full.get("currency") or "USD")

    def _amt(d: dict) -> float | None:
        v = d.get("amount")
        return float(v) if isinstance(v, (int, float)) else None

    cur_amt = _amt(cur)
    full_amt = _amt(full)
    price = format_price(cur_amt, currency) if cur_amt is not None else None
    price_initial = format_price(full_amt, currency) if full_amt is not None else None
    discount = None
    if cur_amt is not None and full_amt and full_amt > 0 and cur_amt < full_amt:
        discount = round(100 * (1 - cur_amt / full_amt))
    return price, price_initial, discount, currency


def _item_from_lookup(obj: dict) -> WishlistItem | None:
    """Build a WishlistItem from one /store/api/lookup result entry."""
    if not isinstance(obj, dict):
        return None
    machine = str(obj.get("machine_name") or "").strip()
    title = str(obj.get("human_name") or "").strip()
    if not machine or not title:
        return None
    image = None
    for key in _IMAGE_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            image = val
            break
    human_url = str(obj.get("human_url") or "").strip()
    slug = human_url or machine
    store_url = f"https://www.humblebundle.com/store/{quote(slug, safe='')}"
    price, price_initial, discount, currency = _price_from_lookup(obj)
    return WishlistItem(
        product_id=machine,
        title=title,
        image_url=image,
        store_url=store_url,
        price=price,
        price_initial=price_initial,
        discount_percent=discount,
        currency=currency,
    )


def _read_wishlist_state(page) -> dict:
    """Read window.models.user_json once the page is past any Cloudflare gate.

    Returns ``{state: 'ok', wishlist: [...slugs]}`` when logged in,
    ``{state: 'signed_out'}`` when the session is gone, or ``{state: 'pending'}``
    while the real page (and user_json) has not loaded yet.
    """
    raw = page.evaluate(
        """() => {
            try {
              const uj = (window.models && window.models.user_json) || null;
              if (!uj) return JSON.stringify({state: 'pending'});
              if (uj.is_logged_in === false) return JSON.stringify({state: 'signed_out'});
              return JSON.stringify({state: 'ok', wishlist: uj.wishlist || []});
            } catch (e) { return JSON.stringify({state: 'pending'}); }
        }""",
        timeout=15,
    )
    try:
        out = json.loads(raw) if isinstance(raw, str) else {}
        return out if isinstance(out, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _lookup_products(page, slugs: list[str]) -> list[dict]:
    """Resolve product slugs to detail dicts via /store/api/lookup (in-page fetch).

    The fetch runs inside the page so it carries the browser's cf_clearance and
    cookies — a plain Python request to the same endpoint gets a Cloudflare 403.
    """
    results: list[dict] = []
    for start in range(0, len(slugs), _LOOKUP_BATCH):
        batch = slugs[start:start + _LOOKUP_BATCH]
        batch_js = json.dumps(batch)
        js = (
            "async () => {"
            f"  const slugs = {batch_js};"
            "  const qs = slugs.map(s => `products[]=${encodeURIComponent(s)}`).join('&');"
            f"  const r = await fetch(`{LOOKUP_PATH}?${{qs}}`, "
            "    {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'include'});"
            "  if (!r.ok) return JSON.stringify({error: r.status});"
            "  const j = await r.json();"
            "  return JSON.stringify(j);"
            "}"
        )
        try:
            raw = page.evaluate(js, timeout=45)
            obj = json.loads(raw) if isinstance(raw, str) else {}
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict) and isinstance(obj.get("result"), list):
            results.extend(r for r in obj["result"] if isinstance(r, dict))
    return results


def _fetch_wishlist(*, dump: bool = False) -> tuple[list[WishlistItem], bool]:
    """Return (items, signed_out) from the headed Humble wishlist page."""
    from auth.cdp_browser import STEALTH_INIT_SCRIPT, close_browser_bounded, launch_persistent_profile

    profile = profile_dir("humble")
    if not profile.exists():
        raise RuntimeError(
            "No saved Humble profile at cache/auth/profiles/humble. "
            "Open the Connections page and connect Humble Bundle first."
        )

    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    )
    try:
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=45_000)

        slugs: list[str] | None = None
        deadline = time.time() + _CLEARANCE_WAIT_SEC
        while time.time() < deadline:
            state = _read_wishlist_state(page)
            if state.get("state") == "signed_out":
                return [], True
            if state.get("state") == "ok":
                slugs = [s for s in (state.get("wishlist") or []) if isinstance(s, str)]
                break
            page.wait_for_timeout(1000)

        if slugs is None:
            raise RuntimeError(
                "Humble wishlist page did not load (Cloudflare challenge or timeout)."
            )

        results = _lookup_products(page, slugs) if slugs else []
        items = [it for it in (_item_from_lookup(o) for o in results) if it]

        if dump:
            dump_json().parent.mkdir(parents=True, exist_ok=True)
            dump_json().write_text(
                json.dumps(
                    {
                        "slug_count": len(slugs),
                        "slugs": slugs,
                        "result_count": len(results),
                        "results": results[:20],
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"  wrote {dump_json()}", flush=True)

        return items, False
    finally:
        close_browser_bounded(ctx, profile=profile)


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
    return {
        "store": "wishlist",
        "wishlist_store": "humble",
        "id": f"humble-{item.product_id}",
        "humble_product_id": item.product_id,
        "name": item.title,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": None,
        "genres": [],
        "tags": [],
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
    }


def _load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_HUMBLE_WISHLIST_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_HUMBLE_WISHLIST_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Humble Store wishlist into games_wishlist_humble.json",
    )
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    add_only_new_arg(parser)
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save resolved wishlist JSON to {dump_json().parent}/",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_humble_wishlist")
    stats = RunStats()
    load_dotenv()

    print("Fetching Humble wishlist via saved store profile...", flush=True)
    try:
        items, signed_out = run_with_heartbeat(
            lambda: _fetch_wishlist(dump=args.dump),
            "Humble wishlist capture",
        )
    except Exception as exc:  # noqa: BLE001
        mark_invalid("humble", error=f"wishlist fetch failed: {exc}")
        stats.error(str(exc))
        return stats.finish("fetch_humble_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if signed_out:
        msg = (
            "Humble session is missing or expired. Open Connections, click Humble Bundle "
            "\u2192 Connect, and sign in at humblebundle.com inside the browser window."
        )
        mark_invalid("humble", error=msg)
        stats.error(msg)
        return stats.finish("fetch_humble_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    print(f"  parsed {len(items)} wishlist items", flush=True)

    if args.dump:
        return stats.finish("fetch_humble_wishlist", t0, exit_code=0, extra="dump only")

    empty_exit = refuse_empty_result(
        items,
        label="Humble wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_HUMBLE_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_humble_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="Humble wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_HUMBLE_WISHLIST_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_humble_wishlist", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []
    for i, item in enumerate(items, 1):
        row_id = f"humble-{item.product_id}"
        cached = existing.get(row_id)
        if args.only_new and cached:
            rows.append(cached)
            continue
        print(f"[{i}/{len(items)}] {item.title}", flush=True)
        hltb = None
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
        "store": "wishlist_humble",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    write_catalog_text(GAMES_HUMBLE_WISHLIST_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(rows)} games to {GAMES_HUMBLE_WISHLIST_JSON}.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_humble_wishlist", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    sys.exit(main())
