#!/usr/bin/env python3
"""Fetch Nintendo.com wish list into games_wishlist_nintendo.json.

The storefront wish list at nintendo.com/us/wish-list/ is a client-rendered
Next.js page. There is no public JSON API documented for third parties; we
reuse the persistent CDP browser profile from the Connections page
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
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import requests
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

GAMES_NINTENDO_WISHLIST_JSON = Path("games_wishlist_nintendo.json")
WISHLIST_URL = "https://www.nintendo.com/us/wish-list/"
# Persisted Apollo query hash for the storefront Wishlist operation (nintendo.com bundle).
WISHLIST_GQL_HASH = (
    "d8e7500d7e8396f682defc557470f865ef7883b933d49c74c685b7f7c89b186b"
)
_WISHLIST_GQL_VARIABLES = {
    "categories": ["ESHOP_PRODUCT", "NOA_PRODUCT"],
    "page": 1,
    "pageSize": 48,
    "includeProductInfo": True,
    "personalized": True,
}


def dump_dir() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "nintendo"


def dump_html() -> Path:
    return dump_dir() / "wishlist_dump.html"


def dump_json() -> Path:
    return dump_dir() / "wishlist_dump.json"
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
    is_dlc: bool = False


def _wishlist_item_is_dlc(obj: dict) -> bool:
    for k in (
        "productType",
        "product_type",
        "contentType",
        "content_type",
        "type",
        "productClass",
        "product_class",
    ):
        val = obj.get(k)
        if isinstance(val, str) and val.lower() in (
            "dlc",
            "aoc",
            "addon",
            "add_on",
            "downloadable_content",
            "downloadablecontent",
        ):
            return True
    title = _first_str(obj, _TITLE_KEYS) or ""
    if re.search(r"\b(dlc|expansion pass|season pass)\b", title, re.I):
        return True
    for nested_key in ("product", "item", "game"):
        nested = obj.get(nested_key)
        if isinstance(nested, dict) and _wishlist_item_is_dlc(nested):
            return True
    return False


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


def _wishlist_entry_dict(raw: dict) -> dict | None:
    """Flatten GraphQL wish-list rows that nest product fields under ``product``."""
    if not isinstance(raw, dict):
        return None
    product = raw.get("product")
    if isinstance(product, dict):
        return {**product, **{k: v for k, v in raw.items() if k != "product"}}
    return raw


def _customer_graphql_authed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    cust = (payload.get("data") or {}).get("customer")
    return isinstance(cust, dict) and bool(cust.get("id"))


def _wishlist_graphql_ok(payload: Any) -> bool:
    """True when the storefront Wishlist query answered (empty list still counts)."""
    if not isinstance(payload, dict):
        return False
    wl = ((payload.get("data") or {}).get("customer") or {}).get("wishList")
    return isinstance(wl, dict) and isinstance(wl.get("items"), list)


def _wishlist_session_authenticated(api_payloads: list[Any]) -> bool:
    return any(_wishlist_graphql_ok(p) for p in api_payloads) or any(
        _customer_graphql_authed(p) for p in api_payloads
    )


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
        is_dlc=_wishlist_item_is_dlc(obj),
    )


def _collect_from_list(items: list) -> list[WishlistItem]:
    out: list[WishlistItem] = []
    seen: set[str] = set()
    for raw in items:
        obj = _wishlist_entry_dict(raw) if isinstance(raw, dict) else None
        if not obj or not _looks_like_wishlist_item(obj):
            continue
        item = _item_from_dict(obj)
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
            sample = [
                obj
                for x in val[:5]
                if isinstance(x, dict)
                for obj in [_wishlist_entry_dict(x)]
                if obj
            ]
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
            wl_items = (
                ((payload.get("data") or {}).get("customer") or {}).get("wishList") or {}
            ).get("items")
            if isinstance(wl_items, list):
                _add_items(_collect_from_list(wl_items))
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


def _is_nintendo_graphql_url(url: str) -> bool:
    return "graph.nintendo.com" in (url or "").lower()


def _is_nintendo_capture_url(url: str) -> bool:
    return _is_nintendo_graphql_url(url)


def _wishlist_capture_complete(html: str, api_payloads: list[Any]) -> bool:
    if any(_wishlist_graphql_ok(p) for p in api_payloads):
        return True
    return bool(parse_wishlist_sources(html, api_payloads))


def _is_stale_nintendo_tab(url: str) -> bool:
    u = (url or "").lower()
    return any(
        tok in u
        for tok in ("authorize", "accounts.nintendo.com/login", "chrome://")
    )


def _close_stale_nintendo_tabs(ctx) -> None:
    """Drop restored OAuth tabs; keep blank tabs when they are the only target."""
    pages = list(ctx.pages)
    keepers = [
        p
        for p in pages
        if "nintendo.com" in (p.url or "").lower() and not _is_stale_nintendo_tab(p.url or "")
    ]
    if not keepers and len(pages) == 1:
        return
    for page in pages:
        if page in keepers:
            continue
        if _is_stale_nintendo_tab(page.url or ""):
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def _pick_render_page(ctx):
    for page in ctx.pages:
        u = (page.url or "").lower()
        if "wish-list" in u and not _is_stale_nintendo_tab(u):
            return page
    for page in ctx.pages:
        u = (page.url or "").lower()
        if "nintendo.com" in u and not _is_stale_nintendo_tab(u):
            return page
    if ctx.pages:
        return ctx.pages[0]
    return ctx.new_page()


def _goto_wishlist_page(page, ctx, *, timeout_ms: int = 15_000):
    """Navigate to the wish-list URL, recovering from dead CDP sessions."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            page.goto(WISHLIST_URL, wait_until="commit", timeout=timeout_ms)
            if not (page.url or "").lower().startswith("chrome://"):
                return page
            last_exc = RuntimeError(f"stuck on {page.url}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if "session" not in str(exc).lower() and attempt == 0:
                raise
        try:
            page = ctx.new_page()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break
    if last_exc:
        raise last_exc
    return page


def _clean_auth_header(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    val = value.strip()
    if not val or val.lower() in {"null", "none", "undefined", "bearer null", "bearer undefined"}:
        return None
    return val


def _note_graphql_auth(resp, auth_state: dict) -> None:
    try:
        req_headers = getattr(getattr(resp, "request", None), "headers", None) or {}
        for key in _GRAPH_AUTH_HEADER_KEYS:
            val = _clean_auth_header(req_headers.get(key))
            if val:
                auth_state.setdefault("headers", {})[key] = val
    except Exception:  # noqa: BLE001
        pass


def _note_tokens_payload(payload: Any, auth_state: dict) -> None:
    if not isinstance(payload, dict):
        return
    tokens = (payload.get("data") or {}).get("tokens")
    if not isinstance(tokens, dict):
        return
    if tokens.get("accessToken"):
        auth_state["bearer"] = tokens["accessToken"]
    if tokens.get("customerToken"):
        auth_state["customer_token"] = tokens["customerToken"]


def _graphql_auth_ready(auth_state: dict) -> bool:
    if _is_guest_storefront_auth({"__typename": auth_state.get("session_typename")}):
        return False
    headers = _build_graphql_auth_headers(auth_state)
    return bool(
        _clean_auth_header(headers.get("authorization"))
        and _clean_auth_header(headers.get("x-customer-token"))
    )


def _direct_wishlist_graphql(ctx, auth_state: dict) -> dict | None:
    """Call the Wishlist persisted query with storefront auth headers."""
    if not _graphql_auth_ready(auth_state):
        return None

    headers = _build_graphql_auth_headers(auth_state)
    headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "origin": "https://www.nintendo.com",
            "referer": WISHLIST_URL,
        }
    )

    extensions = json.dumps(
        {"persistedQuery": {"version": 1, "sha256Hash": WISHLIST_GQL_HASH}},
        separators=(",", ":"),
    )
    variables = json.dumps(_WISHLIST_GQL_VARIABLES, separators=(",", ":"))
    url = (
        "https://graph.nintendo.com/?operationName=Wishlist"
        f"&variables={quote(variables)}&extensions={quote(extensions)}"
    )
    jar = {c["name"]: c["value"] for c in ctx.cookies() if c.get("name")}
    debug: dict[str, Any] = {"status": None, "error": None, "items_len": None}
    try:
        resp = requests.get(url, cookies=jar, headers=headers, timeout=30)
        debug["status"] = resp.status_code
    except Exception as exc:  # noqa: BLE001
        debug["error"] = str(exc)[:200]
        auth_state["_direct_debug"] = debug
        return None
    if resp.status_code >= 400:
        debug["error"] = (resp.text or "")[:200]
        auth_state["_direct_debug"] = debug
        return None
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        debug["error"] = "json_decode"
        auth_state["_direct_debug"] = debug
        return None
    wl_items = (
        ((payload.get("data") or {}).get("customer") or {}).get("wishList") or {}
    ).get("items")
    if isinstance(wl_items, list):
        debug["items_len"] = len(wl_items)
    if payload.get("errors"):
        debug["error"] = str(payload.get("errors"))[:200]
    if _wishlist_graphql_ok(payload):
        auth_state["_direct_debug"] = debug
        return payload
    auth_state["_direct_debug"] = debug
    return None


_GRAPH_AUTH_HEADER_KEYS = (
    "authorization",
    "x-customer-token",
    "x-access-token",
    "x-nintendo-graph",
    "locale",
)


def _read_page_auth_session(page) -> dict[str, Any]:
    try:
        data = page.evaluate(
            """() => {
              const raw = localStorage.getItem('nintendo.customer.session');
              if (!raw) return {};
              try {
                const parsed = JSON.parse(raw);
                return parsed.value || parsed || {};
              } catch (e) {
                return {};
              }
            }"""
        )
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _is_guest_storefront_auth(session: dict[str, Any]) -> bool:
    typename = str(session.get("__typename") or "")
    return "GuestAuthorization" in typename


def _load_storefront_auth_from_page(page, auth_state: dict) -> dict[str, Any]:
    session = _read_page_auth_session(page)
    if session.get("customerToken"):
        auth_state["customer_token"] = session["customerToken"]
    if session.get("accessToken"):
        auth_state["access_token"] = session["accessToken"]
    if session.get("idToken"):
        auth_state["id_token"] = session["idToken"]
    auth_state["session_typename"] = session.get("__typename")
    return session


def _build_graphql_auth_headers(auth_state: dict) -> dict[str, str]:
    headers: dict[str, str] = {
        "content-type": "application/json",
        "x-nintendo-graph": "true",
        "locale": "en-US",
    }
    extra = auth_state.get("headers") or {}
    id_token = auth_state.get("id_token")
    access_token = auth_state.get("access_token") or auth_state.get("bearer")
    customer_token = auth_state.get("customer_token")

    if id_token:
        headers["authorization"] = f"Bearer {id_token}"
    elif extra.get("authorization"):
        headers["authorization"] = extra["authorization"]
    elif access_token:
        headers["authorization"] = f"Bearer {access_token}"

    if access_token:
        headers["x-access-token"] = access_token
    elif extra.get("x-access-token"):
        headers["x-access-token"] = extra["x-access-token"]

    if customer_token:
        headers["x-customer-token"] = customer_token
    elif extra.get("x-customer-token"):
        headers["x-customer-token"] = extra["x-customer-token"]

    for key in _GRAPH_AUTH_HEADER_KEYS:
        if key in extra and key not in headers and _clean_auth_header(extra.get(key)):
            headers[key] = extra[key]
    return headers


def _issue_storefront_tokens_via_page(page, auth_state: dict) -> bool:
    """Reload storefront session tokens from browser storage."""
    session = _load_storefront_auth_from_page(page, auth_state)
    auth_state["_token_debug"] = {
        "session_typename": session.get("__typename"),
        "has_id_token": bool(session.get("idToken")),
        "has_access_token": bool(session.get("accessToken")),
        "has_customer_token": bool(session.get("customerToken")),
    }
    return _graphql_auth_ready(auth_state) and not _is_guest_storefront_auth(session)


def _direct_wishlist_graphql_via_page(page, auth_state: dict) -> dict | None:
    """Replay Wishlist GraphQL from the page context (full browser cookie jar)."""
    if not _graphql_auth_ready(auth_state):
        return None

    extensions = json.dumps(
        {"persistedQuery": {"version": 1, "sha256Hash": WISHLIST_GQL_HASH}},
        separators=(",", ":"),
    )
    variables = json.dumps(_WISHLIST_GQL_VARIABLES, separators=(",", ":"))
    url = (
        "https://graph.nintendo.com/?operationName=Wishlist"
        f"&variables={quote(variables)}&extensions={quote(extensions)}"
    )
    fetch_headers = _build_graphql_auth_headers(auth_state)

    debug: dict[str, Any] = {"via": "page", "status": None, "error": None, "items_len": None}
    try:
        result = page.evaluate(
            f"""async () => {{
              const url = {json.dumps(url)};
              const headers = {json.dumps(fetch_headers)};
              const r = await fetch(url, {{ headers, credentials: "include" }});
              const text = await r.text();
              return {{ status: r.status, text }};
            }}""",
            timeout=30_000,
        )
    except Exception as exc:  # noqa: BLE001
        debug["error"] = str(exc)[:200]
        auth_state["_page_direct_debug"] = debug
        return None

    debug["status"] = result.get("status")
    text = result.get("text") or ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        debug["error"] = text[:200]
        auth_state["_page_direct_debug"] = debug
        return None
    wl_items = (
        ((payload.get("data") or {}).get("customer") or {}).get("wishList") or {}
    ).get("items")
    if isinstance(wl_items, list):
        debug["items_len"] = len(wl_items)
    if payload.get("errors"):
        debug["error"] = str(payload.get("errors"))[:200]
    if _wishlist_graphql_ok(payload):
        auth_state["_page_direct_debug"] = debug
        return payload
    auth_state["_page_direct_debug"] = debug
    return None


def _drain_nintendo_candidates(
    candidates: list[Any],
    *,
    auth_state: dict | None = None,
) -> list[Any]:
    """Parse stashed responses on the main thread (CDP getResponseBody deadlocks on the reader thread)."""
    found: list[Any] = []
    while candidates:
        resp = candidates.pop(0)
        url = resp.url or ""
        try:
            if not _is_nintendo_capture_url(url):
                continue
            if auth_state is not None:
                _note_graphql_auth(resp, auth_state)
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                continue
            body = resp.text()
            if not body:
                continue
            payload = json.loads(body)
            if auth_state is not None:
                _note_tokens_payload(payload, auth_state)
            found.append(payload)
        except Exception:  # noqa: BLE001
            continue
    return found


def _fetch_with_profile(
    *,
    dump: bool = False,
    timeout_s: int = 45,
) -> tuple[str, str, list[Any]]:
    from auth.cdp_browser import close_browser_bounded, launch_persistent_profile

    profile = profile_dir("nintendo_wishlist")
    if not profile.exists():
        raise RuntimeError(
            "No saved Nintendo wishlist profile at cache/auth/profiles/nintendo_wishlist. "
            "Open the Connections page and connect 'Nintendo Store wishlist' first."
        )

    api_payloads: list[Any] = []
    candidates: list[Any] = []
    auth_state: dict[str, Any] = {"headers": {}}

    def _stash_response(response) -> None:
        try:
            if response.status >= 400:
                return
            if not _is_nintendo_capture_url(response.url or ""):
                return
            ct = (response.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            candidates.append(response)
        except Exception:  # noqa: BLE001
            pass

    poll_deadline_s = min(max(timeout_s - 5, 20), 30)
    poll_interval_ms = 500

    ctx = launch_persistent_profile(str(profile), headless=True)
    try:
        _close_stale_nintendo_tabs(ctx)

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
        cookie_parsed = parse_wishlist_sources(req_html, [])
        cookie_signed_out = _signed_out(req_html, WISHLIST_URL)
        need_render = (
            len(req_html) < 2000
            or cookie_signed_out
            or not cookie_parsed
        )
        if need_render:
            page = _pick_render_page(ctx)
            page.on("response", _stash_response)
            render_exc = None
            try:
                page = _goto_wishlist_page(page, ctx)
            except Exception as exc:  # noqa: BLE001
                render_exc = exc
                print(f"  page navigation issue ({exc}); polling GraphQL responses", flush=True)

            url = page.url or WISHLIST_URL
            deadline = time.time() + poll_deadline_s
            while time.time() < deadline:
                drained = _drain_nintendo_candidates(candidates, auth_state=auth_state)
                api_payloads.extend(drained)
                for payload in drained:
                    _note_tokens_payload(payload, auth_state)
                if _wishlist_capture_complete(req_html, api_payloads):
                    break
                if _signed_out(req_html, url):
                    break
                page.wait_for_timeout(poll_interval_ms)

            # Always drain remaining stashed responses (a late wishList response
            # could otherwise be dropped when other payloads were already captured).
            api_payloads.extend(
                _drain_nintendo_candidates(candidates, auth_state=auth_state)
            )

            page_session = _load_storefront_auth_from_page(page, auth_state)
            if (
                not any(_wishlist_graphql_ok(p) for p in api_payloads)
                and _is_guest_storefront_auth(page_session)
            ):
                print(
                    "  storefront session is guest-only; reloading to restore signed-in tokens",
                    flush=True,
                )
                try:
                    page = _goto_wishlist_page(page, ctx)
                except Exception as exc:  # noqa: BLE001
                    print(f"  guest-session reload issue ({exc})", flush=True)
                retry_deadline = time.time() + min(poll_deadline_s, 15)
                while time.time() < retry_deadline:
                    drained = _drain_nintendo_candidates(
                        candidates, auth_state=auth_state
                    )
                    api_payloads.extend(drained)
                    for payload in drained:
                        _note_tokens_payload(payload, auth_state)
                    if any(_wishlist_graphql_ok(p) for p in api_payloads):
                        break
                    page.wait_for_timeout(poll_interval_ms)
                api_payloads.extend(
                    _drain_nintendo_candidates(candidates, auth_state=auth_state)
                )
                page_session = _load_storefront_auth_from_page(page, auth_state)

            # The storefront SPA does not always fire the Wishlist GraphQL query.
            # When token refresh completes but the React hook skips Wishlist, replay
            # the persisted query with the same auth headers/tokens from hydration.
            direct_payload = None
            if (
                not any(_wishlist_graphql_ok(p) for p in api_payloads)
                and _wishlist_session_authenticated(api_payloads)
                and not _signed_out(req_html, page.url or url)
            ):
                for payload in api_payloads:
                    _note_tokens_payload(payload, auth_state)
                if not _graphql_auth_ready(auth_state):
                    token_deadline = time.time() + 10
                    while time.time() < token_deadline:
                        drained = _drain_nintendo_candidates(
                            candidates, auth_state=auth_state
                        )
                        api_payloads.extend(drained)
                        for payload in drained:
                            _note_tokens_payload(payload, auth_state)
                        if _graphql_auth_ready(auth_state) or any(
                            _wishlist_graphql_ok(p) for p in api_payloads
                        ):
                            break
                        page.wait_for_timeout(300)
                if not _graphql_auth_ready(auth_state):
                    _issue_storefront_tokens_via_page(page, auth_state)
                if _graphql_auth_ready(auth_state):
                    print("  wish list query did not fire; calling GraphQL directly", flush=True)
                    direct_payload = _direct_wishlist_graphql(ctx, auth_state)
                    if not direct_payload:
                        direct_payload = _direct_wishlist_graphql_via_page(page, auth_state)
                    if not direct_payload and _issue_storefront_tokens_via_page(page, auth_state):
                        direct_payload = _direct_wishlist_graphql_via_page(page, auth_state)
                    if direct_payload:
                        api_payloads.append(direct_payload)

            try:
                rendered = page.content()
                if len(rendered) > len(page_html):
                    page_html = rendered
                    url = page.url or WISHLIST_URL
            except Exception as exc:  # noqa: BLE001
                if not render_exc:
                    render_exc = exc
                print(f"  page HTML capture skipped ({exc}); using cookie/GraphQL data", flush=True)

        html = page_html if len(page_html) > len(req_html) else req_html

        if dump:
            dump_dir().mkdir(parents=True, exist_ok=True)
            dump_html().write_text(html, encoding="utf-8")
            dump_doc = {
                "url": url,
                "request_html_len": len(req_html),
                "page_html_len": len(page_html),
                "api_payload_count": len(api_payloads),
                "api_payloads": api_payloads[:20],
                "next_data_keys": list((_extract_next_data(html) or {}).keys())[:30],
            }
            dump_json().write_text(
                json.dumps(dump_doc, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  wrote {dump_html()} and {dump_json()}", flush=True)
        return html, url, api_payloads
    finally:
        # Bounded close: never leave an orphan Chrome holding the wishlist profile.
        close_browser_bounded(ctx, profile=profile)



def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
    tags: list[str] = ["dlc"] if item.is_dlc else []
    row = {
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
        "type": "dlc" if item.is_dlc else "game",
        "price": item.price,
        "price_initial": item.price_initial,
        "discount_percent": item.discount_percent,
        "currency": item.currency,
    }
    if item.is_dlc:
        row["nintendo_is_dlc"] = True
    return row


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
    add_only_new_arg(parser)
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save raw HTML + captured JSON to {dump_dir()}/ for debugging",
    )
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_nintendo_wishlist")
    stats = RunStats()

    load_dotenv()
    print("Fetching Nintendo wishlist via headless nintendo.com page...", flush=True)

    try:
        html, url, api_payloads = run_with_heartbeat(
            lambda: _fetch_with_profile(dump=args.dump),
            "Nintendo wishlist capture",
        )
    except Exception as exc:  # noqa: BLE001
        # CDP/transport failures (browser launch, websocket, command timeout) are
        # not auth problems — don't flip the Connections chip to "expired" for them.
        msg = str(exc)
        is_transport = any(
            tok in msg.lower()
            for tok in (
                "cdp command timed out",
                "websocket",
                "browser",
                "debugging endpoint",
                "session with given id",
            )
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

    page_url = (url or "").lower()
    capture_failed = (
        not api_payloads
        and (
            page_url in {"about:blank", ""}
            or page_url.startswith("chrome://")
            or len(html) < 2000
        )
    )
    if capture_failed:
        msg = (
            "Nintendo wishlist browser capture failed (no GraphQL responses). "
            "Retry the fetch; if it keeps failing, reconnect Nintendo Store wishlist."
        )
        stats.error(msg)
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=1)

    if not items and not _wishlist_session_authenticated(api_payloads):
        msg = (
            "Nintendo wish-list session is missing or expired. Open the Connections "
            "page, click 'Nintendo Store wishlist' \u2192 Connect, and sign in on "
            "nintendo.com/us/wish-list/ inside the launched browser window."
        )
        mark_invalid("nintendo_wishlist", error=msg)
        stats.error(msg)
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    if (
        not items
        and _wishlist_session_authenticated(api_payloads)
        and not any(_wishlist_graphql_ok(p) for p in api_payloads)
    ):
        msg = (
            "Nintendo wish-list session is signed in but stuck in a guest token state, "
            "so the storefront never returned wish-list items. Open Connections and "
            "reconnect 'Nintendo Store wishlist'."
        )
        mark_invalid("nintendo_wishlist", error=msg)
        stats.error(msg)
        return stats.finish("fetch_nintendo_wishlist", t0, exit_code=EXIT_CODE_AUTH)

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
