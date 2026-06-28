from __future__ import annotations
import json
import re
from typing import Any
from urllib.parse import quote, urlparse
EPIC_WISHLIST_URL = 'https://store.epicgames.com/en-US/wishlist'

def epic_store_login_url() -> str:
    return f"https://www.epicgames.com/id/login?lang=en-US&noHostRedirect=true&redirectUrl={quote(EPIC_WISHLIST_URL, safe='')}"
_SIGN_IN_RE = re.compile('sign\\s*in|log\\s*in', re.I)
_CF_TITLE_RE = re.compile('<title>\\s*just a moment', re.I)

def is_epic_graphql_url(url: str) -> bool:
    u = (url or '').lower()
    return '/graphql' in u and 'epicgames.com' in u

def wishlist_graphql_ok(payload: Any) -> bool:
    if isinstance(payload, list):
        return any((wishlist_graphql_ok(p) for p in payload))
    if _elements_from_payload(payload):
        return True
    if not isinstance(payload, dict):
        return False
    data = payload.get('data')
    if not isinstance(data, dict):
        return False
    wishlist = data.get('Wishlist')
    if not isinstance(wishlist, dict):
        return False
    items = wishlist.get('wishlistItems')
    return isinstance(items, dict)

def _elements_from_payload(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        out: list[dict] = []
        for entry in payload:
            out.extend(_elements_from_payload(entry))
        return out
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') or payload
    if not isinstance(data, dict):
        return []
    wishlist = data.get('Wishlist')
    if not isinstance(wishlist, dict):
        return []
    items = wishlist.get('wishlistItems')
    if not isinstance(items, dict):
        return []
    elements = items.get('elements')
    if not isinstance(elements, list):
        return []
    return [el for el in elements if isinstance(el, dict)]

def graphql_debug_entry(url: str, payload: Any) -> dict[str, Any]:

    def data_keys(p: Any) -> list[str]:
        if isinstance(p, list):
            keys: list[str] = []
            for entry in p:
                keys.extend(data_keys(entry))
            return keys
        if isinstance(p, dict):
            data = p.get('data')
            if isinstance(data, dict):
                return list(data.keys())
        return []

    def wishlist_sub_keys(p: Any) -> list[str]:
        if isinstance(p, list):
            keys: list[str] = []
            for entry in p:
                keys.extend(wishlist_sub_keys(entry))
            return keys
        if not isinstance(p, dict):
            return []
        data = p.get('data')
        if not isinstance(data, dict):
            return []
        wishlist = data.get('Wishlist')
        if not isinstance(wishlist, dict):
            return []
        return list(wishlist.keys())
    return {'url': url, 'matched': wishlist_graphql_ok(payload), 'data_keys': data_keys(payload), 'wishlist_sub_keys': wishlist_sub_keys(payload)}
_GET_WISHLIST_QUERY_KEY = '"queryKey":["getWishlist"'

def _parse_json_value(text: str, start: int) -> tuple[Any | None, int]:
    pos = start
    while pos < len(text) and text[pos] in ' \t\n\r':
        pos += 1
    if pos >= len(text) or text[pos] not in '{[':
        return (None, pos)
    open_ch = text[pos]
    close_ch = '}' if open_ch == '{' else ']'
    depth = 0
    in_str = False
    escape = False
    for i in range(pos, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return (json.loads(text[pos:i + 1]), i + 1)
                except json.JSONDecodeError:
                    return (None, i + 1)
    return (None, len(text))

def extract_wishlist_payloads_from_html(html: str) -> list[dict[str, Any]]:
    body = html or ''
    payloads: list[dict[str, Any]] = []
    idx = 0
    while True:
        pos = body.find(_GET_WISHLIST_QUERY_KEY, idx)
        if pos == -1:
            break
        window_start = max(0, pos - 12000)
        window = body[window_start:pos]
        for marker in ('"data":{"Wishlist"', '"data": {"Wishlist"'):
            rel = window.rfind(marker)
            if rel == -1:
                continue
            data_pos = window_start + rel + len('"data":')
            data_obj, _ = _parse_json_value(body, data_pos)
            if not isinstance(data_obj, dict):
                continue
            wishlist = data_obj.get('Wishlist')
            if not isinstance(wishlist, dict):
                continue
            items = wishlist.get('wishlistItems')
            if not isinstance(items, dict):
                continue
            payloads.append({'data': {'Wishlist': wishlist}})
            break
        idx = pos + len(_GET_WISHLIST_QUERY_KEY)
    return payloads

def extract_catalog_offers_from_html(html: str) -> dict[str, dict[str, Any]]:
    body = html or ''
    offers: dict[str, dict[str, Any]] = {}
    idx = 0
    marker = '"catalogOffer"'
    while True:
        pos = body.find(marker, idx)
        if pos == -1:
            break
        brace = body.find('{', pos + len(marker))
        if brace == -1:
            idx = pos + 1
            continue
        obj, end = _parse_json_value(body, brace)
        if isinstance(obj, dict):
            oid = obj.get('id')
            if oid:
                offers[str(oid)] = obj
        idx = max(end, pos + 1)
    return offers

def enrich_wishlist_elements_with_catalog(html: str, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    offers = extract_catalog_offers_from_html(html)
    if not offers:
        return elements
    out: list[dict[str, Any]] = []
    for el in elements:
        row = dict(el)
        if not row.get('offer'):
            oid = row.get('offerId')
            if oid and str(oid) in offers:
                row['offer'] = offers[str(oid)]
        out.append(row)
    return out

def wishlist_capture_complete_from_html(html: str) -> bool:
    return any((wishlist_graphql_ok(p) for p in extract_wishlist_payloads_from_html(html)))

def cloudflare_interstitial(html: str, url: str) -> bool:
    u = (url or '').lower()
    if '/cdn-cgi/challenge' in u:
        return True
    body = html or ''
    if _CF_TITLE_RE.search(body):
        return True
    if 'cf_challenge_container' in body or 'cf_challenge_text' in body:
        return True
    return False

def storefront_bounced_to_home(url: str) -> bool:
    parsed = urlparse(url or '')
    host = (parsed.netloc or '').lower()
    path = (parsed.path or '').lower()
    return 'store.epicgames.com' in host and 'wishlist' not in path

def storefront_signed_out(html: str, url: str) -> bool:
    u = (url or '').lower()
    if 'id.epicgames.com/login' in u or ('/login' in u and 'store' not in u):
        return True
    if cloudflare_interstitial(html, url):
        return False
    if storefront_bounced_to_home(url):
        return True
    body = html or ''
    if _SIGN_IN_RE.search(body) and (not _CF_TITLE_RE.search(body)):
        if storefront_bounced_to_home(url):
            return True
        if 'wishlist' not in body.lower():
            return True
    return False

def storefront_auth_blocked(html: str, url: str) -> bool:
    return cloudflare_interstitial(html, url) or storefront_signed_out(html, url)

def storefront_auth_error_message(html: str, url: str) -> str:
    if cloudflare_interstitial(html, url):
        return 'Cloudflare blocked the Epic wishlist fetch. Open Connections, click Epic (wishlist) → Connect, complete any Cloudflare check, sign in, open Wishlist, and wait for it to finish loading.'
    if storefront_bounced_to_home(url):
        return 'Epic storefront session is not active (bounced to store home). Open Connections, click Epic (wishlist) → Connect, sign in, open Wishlist from the menu, and wait for your tiles to load before the window closes.'
    return 'Epic storefront session is missing or expired. Open Connections, click Epic (wishlist) → Connect, sign in at store.epicgames.com/wishlist (clear Cloudflare if shown), and wait for the wishlist to load.'