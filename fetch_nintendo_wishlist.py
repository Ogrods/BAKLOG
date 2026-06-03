#!/usr/bin/env python3
"""Fetch Nintendo.com wish list into games_wishlist_nintendo.json.

The storefront wish list at nintendo.com/us/wish-list/ is a client-rendered
Next.js page. There is no public JSON API documented for third parties; we
reuse the persistent Playwright profile from the Connections page
(``cache/auth/profiles/nintendo_wishlist``), load the page headlessly, and
parse embedded JSON (``__NEXT_DATA__``) plus any wishlist XHR responses
captured during hydration.

Separate from the ``nintendo`` library provider, which authenticates
``ec.nintendo.com`` for eShop transaction history via ``NINTENDO_COOKIE``.
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
from urllib.parse import urljoin

from dotenv import load_dotenv

from auth import mark_invalid
from auth.secrets import profile_dir
from fetchers._base import add_allow_empty_arg, refuse_drift_result, refuse_empty_result, catalog_file, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from shared.money import format_price, normalize_currency_code

GAMES_NINTENDO_WISHLIST_JSON = Path("games_wishlist_nintendo.json")
WISHLIST_URL = "https://www.nintendo.com/us/wish-list/"
DUMP_DIR = Path("cache/nintendo")
DUMP_HTML = DUMP_DIR / "wishlist_dump.html"
DUMP_JSON = DUMP_DIR / "wishlist_dump.json"
HLTB_DELAY_SEC = 1.0

_NSUID_RE = re.compile(r"^7\d{12,14}$")
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>',
    re.DOTALL | re.IGNORECASE,
)
_SIGN_IN_ONLY_RE = re.compile(
    r"sign\s*in.*nintendo\s*account|log\s*in.*nintendo\s*account",
    re.IGNORECASE | re.DOTALL,
)

_ID_KEYS = frozenset(
    {
        "nsuid", "nsUid", "NSUID", "productId", "product_id", "id", "sku", "fs_id",
    }
)
_TITLE_KEYS = frozenset(
    {
        "title", "name", "displayName", "productName", "productTitle", "label",
    }
)
_IMAGE_KEYS = frozenset(
    {
        "imageUrl", "image_url", "image", "thumbnail", "thumbnailUrl", "boxArt",
        "heroBanner", "url",
    }
)
_URL_KEYS = frozenset({"url", "href", "link", "productUrl", "product_url", "path"})
_PRICE_KEYS = frozenset(
    {
        "price", "prices", "regularPrice", "discountPrice", "salePrice",
        "currentPrice", "msrp", "listPrice",
    }
)


@dataclass
class WishlistItem:
    product_id: str
    title: str
    image_url: str | None
    store_url: str
    release_date: str | None
    genres: list[str]
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


def _parse_json_assignment(html: str, marker: str) -> dict | None:
    idx = html.find(marker)
    if idx == -1:
        return None
    eq = html.find("=", idx + len(marker))
    if eq == -1:
        return None
    start = eq + 1
    while start < len(html) and html[start] in " \t\r\n":
        start += 1
    if start >= len(html) or html[start] != "{":
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _extract_next_data(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


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


def _first_str(obj: dict, keys: frozenset[str]) -> str | None:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _normalize_product_id(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if _NSUID_RE.fullmatch(s):
        return s
    if s.isdigit() and len(s) >= 12 and s.startswith("7"):
        return s
    return None


def _pick_image(obj: dict) -> str | None:
    for k in _IMAGE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip().startswith(("http", "//", "/")):
            u = v.strip()
            if u.startswith("//"):
                return "https:" + u
            if u.startswith("/"):
                return urljoin("https://www.nintendo.com", u)
            return u if u.startswith("http") else None
        if isinstance(v, dict):
            inner = _pick_image(v)
            if inner:
                return inner
    images = obj.get("images")
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                inner = _pick_image(img)
                if inner:
                    return inner
    return None


def _parse_price_value(raw: Any) -> tuple[float | None, str | None]:
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), None
    if isinstance(raw, str):
        s = raw.strip().replace("$", "").replace(",", "")
        try:
            return float(s), None
        except ValueError:
            return None, None
    if isinstance(raw, dict):
        currency = (
            raw.get("currency")
            or raw.get("currencyCode")
            or raw.get("CurrencyCode")
        )
        for key in ("rawValue", "amount", "value", "price", "formattedValue"):
            v = raw.get(key)
            if isinstance(v, (int, float)):
                return float(v), str(currency) if currency else None
            if isinstance(v, str):
                parsed, _ = _parse_price_value(v)
                if parsed is not None:
                    return parsed, str(currency) if currency else None
    return None, None


def _pick_prices(obj: dict) -> tuple[str | None, str | None, int | None, str | None]:
    sale = None
    regular = None
    currency = None
    for k in _PRICE_KEYS:
        v = obj.get(k)
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                sub = sub_v if isinstance(sub_v, dict) else {sub_k: sub_v}
                amt, cur = _parse_price_value(sub)
                if cur and not currency:
                    currency = cur
                sk = sub_k.lower()
                if amt is None:
                    continue
                if "discount" in sk or "sale" in sk or "current" in sk:
                    sale = amt if sale is None else sale
                elif "regular" in sk or "msrp" in sk or "list" in sk:
                    regular = amt if regular is None else regular
        else:
            amt, cur = _parse_price_value(v)
            if cur and not currency:
                currency = cur
            if amt is not None and sale is None:
                sale = amt

    cur_norm = normalize_currency_code(currency)

    def _fmt(v: float | None) -> str | None:
        if v is None:
            return None
        if v == 0:
            return "Free"
        return format_price(v, cur_norm)

    discount = None
    if sale is not None and regular is not None and regular > 0 and sale < regular:
        discount = round(100 * (1 - sale / regular))
    return _fmt(sale), _fmt(regular), discount, cur_norm


def _store_url(product_id: str, path_or_url: str | None) -> str:
    if path_or_url:
        u = path_or_url.strip()
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            return urljoin("https://www.nintendo.com", u)
    if product_id:
        return f"https://www.nintendo.com/us/store/products/game/{product_id}/"
    return WISHLIST_URL


def _looks_like_wishlist_item(obj: dict) -> bool:
    pid = None
    for k in _ID_KEYS:
        pid = _normalize_product_id(obj.get(k))
        if pid:
            break
    title = _first_str(obj, _TITLE_KEYS)
    return bool(pid and title)


def _item_from_dict(obj: dict) -> WishlistItem | None:
    pid = None
    for k in _ID_KEYS:
        pid = _normalize_product_id(obj.get(k))
        if pid:
            break
    title = _first_str(obj, _TITLE_KEYS)
    if not pid or not title:
        return None
    path = _first_str(obj, _URL_KEYS)
    price, price_initial, discount, currency = _pick_prices(obj)
    release = obj.get("releaseDate") or obj.get("release_date") or obj.get("releaseDateDisplay")
    if isinstance(release, dict):
        release = release.get("date") or release.get("rawValue")
    release_s = str(release)[:10] if isinstance(release, str) and release.strip() else None
    genres: list[str] = []
    for gk in ("genres", "categories", "gameGenre", "genre"):
        gr = obj.get(gk)
        if isinstance(gr, list):
            for g in gr:
                if isinstance(g, str) and g.strip():
                    genres.append(g.strip())
                elif isinstance(g, dict):
                    gn = g.get("name") or g.get("label")
                    if isinstance(gn, str) and gn.strip():
                        genres.append(gn.strip())
        elif isinstance(gr, str) and gr.strip():
            genres.append(gr.strip())
    return WishlistItem(
        product_id=pid,
        title=title,
        image_url=_pick_image(obj),
        store_url=_store_url(pid, path),
        release_date=release_s,
        genres=list(dict.fromkeys(genres)),
        price=price,
        price_initial=price_initial,
        discount_percent=discount,
        currency=currency,
    )


def _collect_from_list(items: list) -> list[WishlistItem]:
    out: list[WishlistItem] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict) or not _looks_like_wishlist_item(raw):
            continue
        item = _item_from_dict(raw)
        if item and item.product_id not in seen:
            seen.add(item.product_id)
            out.append(item)
    return out


def _find_wishlist_lists(node: Any) -> list[list]:
    """Find list nodes that look like wishlist item arrays."""
    hits: list[list] = []
    for n in _walk(node):
        if not isinstance(n, dict):
            continue
        for key, val in n.items():
            if not isinstance(val, list) or len(val) == 0:
                continue
            kl = key.lower()
            if not any(tok in kl for tok in ("wish", "item", "product", "game")):
                continue
            sample = [x for x in val[:5] if isinstance(x, dict)]
            if not sample:
                continue
            if sum(1 for s in sample if _looks_like_wishlist_item(s)) >= max(1, len(sample) // 2):
                hits.append(val)
    return hits


def parse_wishlist_sources(html: str, api_payloads: list[Any]) -> list[WishlistItem]:
    """Parse wishlist rows from SSR HTML and captured JSON responses."""
    found: dict[str, WishlistItem] = {}

    def _add_items(items: list[WishlistItem]) -> None:
        for it in items:
            found.setdefault(it.product_id, it)

    next_data = _extract_next_data(html)
    if next_data:
        for lst in _find_wishlist_lists(next_data):
            _add_items(_collect_from_list(lst))

    preloaded = _parse_json_assignment(html, "window.__PRELOADED_STATE__")
    if preloaded:
        for lst in _find_wishlist_lists(preloaded):
            _add_items(_collect_from_list(lst))

    for payload in api_payloads:
        if isinstance(payload, dict):
            for lst in _find_wishlist_lists(payload):
                _add_items(_collect_from_list(lst))
        elif isinstance(payload, list):
            _add_items(_collect_from_list(payload))

    # Link href fallback: product tiles in SSR shell
    for m in re.finditer(
        r'href="(/us/store/products/[^"]+)"[^>]*>(?:[^<]*<[^>]+>)*[^<]*<[^>]*>([^<]{2,120})</',
        html,
        re.IGNORECASE,
    ):
        path, title = m.group(1), m.group(2).strip()
        pid_match = re.search(r"7\d{12,14}", path)
        pid = pid_match.group(0) if pid_match else re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:40]
        if pid in found:
            continue
        found[pid] = WishlistItem(
            product_id=pid,
            title=title,
            image_url=None,
            store_url=urljoin("https://www.nintendo.com", path),
            release_date=None,
            genres=[],
            price=None,
            price_initial=None,
            discount_percent=None,
            currency=None,
        )

    return sorted(found.values(), key=lambda x: x.title.lower())


def _signed_out(html: str, url: str) -> bool:
    u = (url or "").lower()
    if "accounts.nintendo.com/login" in u:
        return True
    if _SIGN_IN_ONLY_RE.search(html or "") and "/store/products/" not in (html or ""):
        return True
    return False


def _fetch_with_profile(
    *,
    dump: bool = False,
    timeout_s: int = 45,
) -> tuple[str, str, list[Any]]:
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir("nintendo_wishlist")
    if not profile.exists():
        raise RuntimeError(
            "No saved Nintendo wishlist profile at cache/auth/profiles/nintendo_wishlist. "
            "Open the Connections page and connect 'Nintendo Store wishlist' first."
        )

    api_payloads: list[Any] = []

    def _maybe_capture(response) -> None:
        try:
            url = (response.url or "").lower()
            if response.status >= 400:
                return
            if "wish" not in url and "wishlist" not in url:
                return
            ct = (response.headers.get("content-type") or "").lower()
            if "json" not in ct and "javascript" not in ct:
                return
            body = response.json()
            api_payloads.append(body)
        except Exception:  # noqa: BLE001
            pass

    with launch_persistent_profile(str(profile), headless=True) as ctx:
        # Cookie-first: a plain authenticated GET returns the SSR HTML without
        # booting the heavy Next.js client, which is faster and avoids the
        # renderer-stall path. Only fall back to a full page render when this
        # HTML is too short or looks signed-out.
        req_html = ""
        try:
            resp = ctx.request.get(WISHLIST_URL, timeout=timeout_s * 1000)
            if resp.status < 400:
                req_html = resp.text()
            else:
                print(f"  cookie GET returned HTTP {resp.status}; will try full render", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  cookie GET failed ({exc}); will try full render", flush=True)

        url = WISHLIST_URL
        page_html = ""
        need_render = (
            len(req_html) < 2000
            or _signed_out(req_html, WISHLIST_URL)
            or not parse_wishlist_sources(req_html, [])
        )
        if need_render:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", _maybe_capture)
            try:
                page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                page.wait_for_timeout(3000)
                page_html = page.content()
                url = page.url or WISHLIST_URL
            except Exception as exc:  # noqa: BLE001
                print(f"  full page render failed ({exc}); using cookie HTML", flush=True)

        html = page_html if len(page_html) > len(req_html) else req_html

        if dump:
            DUMP_DIR.mkdir(parents=True, exist_ok=True)
            DUMP_HTML.write_text(html, encoding="utf-8")
            dump_doc = {
                "url": url,
                "request_html_len": len(req_html),
                "page_html_len": len(page_html),
                "api_payload_count": len(api_payloads),
                "api_payloads": api_payloads[:20],
                "next_data_keys": list((_extract_next_data(html) or {}).keys())[:30],
            }
            DUMP_JSON.write_text(
                json.dumps(dump_doc, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  wrote {DUMP_HTML} and {DUMP_JSON}", flush=True)

        return html, url, api_payloads


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
    return {
        "store": "wishlist",
        "wishlist_store": "nintendo",
        "id": f"nintendo-{item.product_id}",
        "nintendo_product_id": item.product_id,
        "name": item.title,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": item.release_date,
        "genres": list(dict.fromkeys(item.genres)),
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
    if not catalog_file(GAMES_NINTENDO_WISHLIST_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_NINTENDO_WISHLIST_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Nintendo.com wish list into games_wishlist_nintendo.json",
    )
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save raw HTML + captured JSON to {DUMP_DIR}/ for debugging",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_nintendo_wishlist")
    stats = RunStats()

    load_dotenv()
    print("Fetching Nintendo wishlist via headless nintendo.com page...", flush=True)

    try:
        html, url, api_payloads = _fetch_with_profile(dump=args.dump)
    except Exception as exc:  # noqa: BLE001
        # CDP/transport failures (browser launch, websocket, command timeout) are
        # not auth problems — don't flip the Connections chip to "expired" for them.
        msg = str(exc)
        is_transport = any(
            tok in msg.lower()
            for tok in ("cdp command timed out", "websocket", "browser", "debugging endpoint")
        )
        if is_transport:
            stats.error(f"wishlist fetch transport error: {msg}")
            return stats.finish("fetch_nintendo_wishlist", t0, exit_code=1)
        mark_invalid("nintendo_wishlist", error=f"wishlist page fetch failed: {msg}")
        stats.error(msg)
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if _signed_out(html, url):
        msg = (
            "Nintendo wish-list session is missing or expired. Open the Connections "
            "page, click 'Nintendo Store wishlist' \u2192 Connect, and sign in on "
            "nintendo.com/us/wish-list/ inside the launched browser window."
        )
        mark_invalid("nintendo_wishlist", error=msg)
        stats.error(msg)
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    items = parse_wishlist_sources(html, api_payloads)
    print(
        f"  parsed {len(items)} wishlist items "
        f"({len(api_payloads)} captured JSON response(s))",
        flush=True,
    )

    if args.dump:
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=0, extra="dump only")

    empty_exit = refuse_empty_result(
        items,
        label="Nintendo wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_NINTENDO_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="Nintendo wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_NINTENDO_WISHLIST_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []

    for i, item in enumerate(items, 1):
        row_id = f"nintendo-{item.product_id}"
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
        "store": "wishlist_nintendo",
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    write_catalog_text(GAMES_NINTENDO_WISHLIST_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(rows)} games to {GAMES_NINTENDO_WISHLIST_JSON}.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_nintendo_wishlist", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    sys.exit(main())
