#!/usr/bin/env python3
"""Fetch Humble Store wishlist into games_wishlist_humble.json.

Reuses the saved Humble browser profile (same login as fetch_humble.py).
Loads https://www.humblebundle.com/store/wishlist and parses embedded JSON
plus any wishlist XHR responses captured during hydration.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin

from dotenv import load_dotenv

from auth import mark_invalid
from fetch_humble import _launch_humble_ctx
from fetchers._base import add_allow_empty_arg, refuse_drift_result, refuse_empty_result, catalog_file, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from shared.money import format_price, normalize_currency_code

GAMES_HUMBLE_WISHLIST_JSON = Path("games_wishlist_humble.json")
WISHLIST_URL = "https://www.humblebundle.com/store/wishlist"
DUMP_HTML = Path("cache/humble/wishlist_dump.html")
DUMP_JSON = Path("cache/humble/wishlist_dump.json")
HLTB_DELAY_SEC = 1.0

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>',
    re.DOTALL | re.IGNORECASE,
)
_SIGN_IN_RE = re.compile(r"sign\s*in|log\s*in", re.I)


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


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _walk(node: Any, depth: int = 0, max_depth: int = 14) -> Iterable[Any]:
    if depth > max_depth or node is None:
        return
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v, depth + 1, max_depth)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, depth + 1, max_depth)


def _extract_next_data(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _product_id(obj: dict) -> str | None:
    for key in ("machine_name", "machineName", "product_machine_name", "slug", "id"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            s = val.strip()
            if len(s) >= 2 and not s.isdigit():
                return s
    return None


def _title(obj: dict) -> str | None:
    for key in ("human_name", "humanName", "title", "name", "display_name", "product_name"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _image(obj: dict) -> str | None:
    for key in ("tile_image", "tileImage", "icon", "image", "thumbnail", "box_art"):
        val = obj.get(key)
        if isinstance(val, str) and val.startswith(("http", "//")):
            return val if val.startswith("http") else "https:" + val
        if isinstance(val, dict):
            u = val.get("url") or val.get("path")
            if isinstance(u, str) and u.startswith("http"):
                return u
    return None


def _prices(obj: dict) -> tuple[str | None, str | None, int | None, str | None]:
    current = obj.get("current_price") or obj.get("price") or obj.get("sale_price")
    full = obj.get("full_price") or obj.get("msrp") or obj.get("regular_price")
    currency = obj.get("currency") or "USD"

    def _num(v: Any) -> float | None:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            for k in ("amount", "value", "raw"):
                if isinstance(v.get(k), (int, float)):
                    return float(v[k])
        return None

    cur = _num(current)
    reg = _num(full)
    if cur is None and isinstance(obj.get("price_info"), dict):
        pi = obj["price_info"]
        cur = _num(pi.get("current"))
        reg = _num(pi.get("full")) or reg
        currency = pi.get("currency") or currency

    cur_norm = normalize_currency_code(currency)

    def _fmt(v: float | None) -> str | None:
        if v is None:
            return None
        return format_price(v, cur_norm)

    discount = None
    if cur is not None and reg is not None and reg > 0 and cur < reg:
        discount = round(100 * (1 - cur / reg))
    return _fmt(cur), _fmt(reg), discount, cur_norm


def _looks_like_product(obj: dict) -> bool:
    pid = _product_id(obj)
    title = _title(obj)
    return bool(pid and title)


def _item_from_dict(obj: dict) -> WishlistItem | None:
    pid = _product_id(obj)
    title = _title(obj)
    if not pid or not title:
        return None
    price, price_initial, discount, currency = _prices(obj)
    path = obj.get("url") or obj.get("link")
    if isinstance(path, str) and path.startswith("/"):
        store_url = urljoin("https://www.humblebundle.com", path)
    else:
        store_url = f"https://www.humblebundle.com/store/{quote(pid, safe='')}"
    return WishlistItem(
        product_id=pid,
        title=title,
        image_url=_image(obj),
        store_url=store_url,
        price=price,
        price_initial=price_initial,
        discount_percent=discount,
        currency=currency,
    )


def _collect_product_lists(node: Any) -> list[list]:
    hits: list[list] = []
    for n in _walk(node):
        if not isinstance(n, dict):
            continue
        for key, val in n.items():
            if not isinstance(val, list) or len(val) == 0:
                continue
            kl = key.lower()
            if "wish" not in kl and "product" not in kl and "item" not in kl:
                continue
            sample = [x for x in val[:8] if isinstance(x, dict)]
            if not sample:
                continue
            if sum(1 for s in sample if _looks_like_product(s)) >= max(1, len(sample) // 2):
                hits.append(val)
    return hits


def parse_wishlist_sources(html: str, api_payloads: list[Any]) -> list[WishlistItem]:
    found: dict[str, WishlistItem] = {}

    def _add(items: list[WishlistItem]) -> None:
        for it in items:
            found.setdefault(it.product_id, it)

    next_data = _extract_next_data(html)
    if next_data:
        for lst in _collect_product_lists(next_data):
            _add([x for x in (_item_from_dict(o) for o in lst) if x])

    for payload in api_payloads:
        if isinstance(payload, dict):
            for lst in _collect_product_lists(payload):
                _add([x for x in (_item_from_dict(o) for o in lst) if x])
            # Flat wishlist array at top level
            for key in ("wishlist", "products", "items"):
                val = payload.get(key)
                if isinstance(val, list):
                    _add([x for x in (_item_from_dict(o) for o in val if isinstance(o, dict)) if x])
        elif isinstance(payload, list):
            _add([x for x in (_item_from_dict(o) for o in payload if isinstance(o, dict)) if x])

    return sorted(found.values(), key=lambda x: x.title.lower())


def _signed_out_page(html: str, url: str) -> bool:
    u = (url or "").lower()
    if "login" in u and "wishlist" not in u:
        return True
    if _SIGN_IN_RE.search(html or "") and "wishlist" not in (html or "").lower():
        return True
    return False


def _fetch_wishlist(*, dump: bool = False) -> tuple[str, str, list[Any]]:
    api_payloads: list[Any] = []

    def _capture(resp) -> None:
        try:
            url = (resp.url or "").lower()
            if resp.status >= 400:
                return
            if "wishlist" not in url and "wish" not in url:
                return
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            api_payloads.append(resp.json())
        except Exception:  # noqa: BLE001
            pass

    with _launch_humble_ctx(headless=True) as ctx:
        req_html = ""
        try:
            resp = ctx.request.get(WISHLIST_URL, timeout=45_000)
            if resp.status < 400:
                req_html = resp.text()
        except Exception:  # noqa: BLE001
            pass

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", _capture)
        page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(3000)
        page_html = page.content()
        url = page.url or WISHLIST_URL
        html = page_html if len(page_html) > len(req_html) else req_html

        if dump:
            DUMP_HTML.parent.mkdir(parents=True, exist_ok=True)
            DUMP_HTML.write_text(html, encoding="utf-8")
            DUMP_JSON.write_text(
                json.dumps(
                    {
                        "url": url,
                        "api_payload_count": len(api_payloads),
                        "api_payloads": api_payloads[:20],
                        "next_data_keys": list((_extract_next_data(html) or {}).keys())[:30],
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"  wrote {DUMP_HTML} and {DUMP_JSON}", flush=True)

        return html, url, api_payloads


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
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save raw HTML + JSON to {DUMP_HTML.parent}/",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_humble_wishlist")
    stats = RunStats()
    load_dotenv()

    print("Fetching Humble wishlist via headless store page...", flush=True)
    try:
        html, url, api_payloads = _fetch_wishlist(dump=args.dump)
    except Exception as exc:  # noqa: BLE001
        mark_invalid("humble", error=f"wishlist fetch failed: {exc}")
        stats.error(str(exc))
        return stats.finish("fetch_humble_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if _signed_out_page(html, url):
        msg = (
            "Humble session is missing or expired. Open Connections, click Humble Bundle "
            "\u2192 Connect, and sign in at humblebundle.com inside the browser window."
        )
        mark_invalid("humble", error=msg)
        stats.error(msg)
        return stats.finish("fetch_humble_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    items = parse_wishlist_sources(html, api_payloads)
    print(
        f"  parsed {len(items)} wishlist items ({len(api_payloads)} captured JSON responses)",
        flush=True,
    )

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
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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
