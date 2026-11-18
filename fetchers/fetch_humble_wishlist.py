#!/usr/bin/env python3
"""Fetch Humble Store wishlist into games_wishlist_humble.json.

Reuses the saved Humble browser profile (same login as fetch_humble.py).

After Humble's Nov 2026 redesign the legacy ``window.models.user_json.wishlist``
embed is gone from the Next.js store shell, and Humble currently serves a
"Wishlist Will Be Back ASAP" interstitial. This fetcher mirrors the library
path: session-status check, Next.js action sniffing (with live action-id
discovery), DOM product-link fallback, then ``/store/api/lookup`` for
price/image enrichment when the list payload is slug-only. The legacy
``user_json`` read is still attempted for compatibility if Humble restores it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

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
SESSION_STATUS_URL = "https://www.humblebundle.com/api/auth/session-status"

# Last-known-good placeholder; runtime discovery from wishlist/store chunks wins.
# Humble has not published a stable list action while wishlist is offline.
FILTER_WISHLIST_ACTION = ""
_WISHLIST_ACTION_NAME_RE = re.compile(
    r'''["']([a-f0-9]{40,44})["'].{0,200}?findSourceMapURL,"([A-Za-z0-9_]*[Ww]ish[A-Za-z0-9_]*)"''',
    re.DOTALL,
)
_WISHLIST_ACTION_NAME_RE_ALT = re.compile(
    r'''["']([a-f0-9]{40,44})["'].{0,160}?([A-Za-z_][A-Za-z0-9_]*[Ww]ish(?:[Ll]ist)?[A-Za-z0-9_]*)''',
    re.DOTALL,
)

_WISHLIST_UNAVAILABLE_MARKERS = (
    "Wishlist Will Be Back ASAP",
    "working to get wishlist back up",
    "get wishlist back up as soon as possible",
)

# Headed but off-screen: same real-browser fingerprint as the connect window
# (so Cloudflare lets the store API through) without stealing focus.
_WL_WINDOW_POS = (-32000, 0)
_WL_WINDOW_SIZE = (1280, 900)
_CLEARANCE_WAIT_SEC = 45
_LOOKUP_BATCH = 20

HLTB_DELAY_SEC = 1.0

# Preferred product image fields from the lookup API (largest first).
_IMAGE_KEYS = (
    "large_capsule",
    "featured_image_recommendation",
    "standard_carousel_image",
    "icon",
)

class WishlistUnavailableError(RuntimeError):
    """Humble is serving the redesign interstitial instead of a wishlist list."""


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


def _item_from_wishlist_row(obj: dict) -> WishlistItem | None:
    """Map one action/DOM wishlist row into a WishlistItem (prices may be missing)."""
    if not isinstance(obj, dict):
        return None
    machine = str(
        obj.get("machine_name")
        or obj.get("product_id")
        or obj.get("id")
        or obj.get("slug")
        or obj.get("human_url")
        or ""
    ).strip()
    title = str(
        obj.get("human_name")
        or obj.get("title")
        or obj.get("name")
        or machine
        or ""
    ).strip()
    if not machine:
        return None
    image = None
    for key in _IMAGE_KEYS + ("image", "header_image", "image_url"):
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            image = val
            break
    human_url = str(obj.get("human_url") or obj.get("slug") or "").strip()
    slug = human_url or machine
    store_url = str(obj.get("store_url") or obj.get("href") or "").strip()
    if not store_url.startswith("http"):
        store_url = f"https://www.humblebundle.com/store/{quote(slug, safe='')}"
    price, price_initial, discount, currency = _price_from_lookup(obj)
    if not title:
        title = machine
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


def text_shows_wishlist_unavailable(text: str) -> bool:
    """True when Humble is serving the redesign interstitial instead of a list."""
    if not text:
        return False
    return any(marker in text for marker in _WISHLIST_UNAVAILABLE_MARKERS)


def _page_shows_wishlist_unavailable(page) -> bool:
    try:
        raw = page.evaluate(
            """() => {
              const t = ((document.body && document.body.innerText) || '')
                + ' ' + (document.title || '');
              return t;
            }""",
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return False
    return text_shows_wishlist_unavailable(raw if isinstance(raw, str) else "")


def _page_looks_signed_out(page) -> bool:
    raw = getattr(page, "url", None) or ""
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host == "auth.humblebundle.com":
        return True
    if path.rstrip("/").endswith("/login") or "/login" in path.split("/"):
        return True
    return False


def _discover_wishlist_action_ids(text: str) -> list[str]:
    """Extract Next.js action ids whose export name looks wishlist-related."""
    if not text:
        return []
    found: list[str] = []
    for pat in (_WISHLIST_ACTION_NAME_RE, _WISHLIST_ACTION_NAME_RE_ALT):
        for m in pat.finditer(text):
            name = m.group(2)
            if re.search(r"wish", name, re.I):
                found.append(m.group(1))
    # Also accept createServerReference("hash", …, "…Wish…")
    for m in re.finditer(
        r'findSourceMapURL,"([A-Za-z0-9_]*[Ww]ish[A-Za-z0-9_]*)"',
        text,
    ):
        # walk backward for nearest hash
        start = max(0, m.start() - 120)
        hm = re.search(r'["\']([a-f0-9]{40,44})["\']', text[start : m.start()])
        if hm:
            found.append(hm.group(1))
    # Dedupe preserving order
    out: list[str] = []
    seen: set[str] = set()
    for aid in found:
        if aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def _discover_wishlist_actions_from_page(page, request_client=None) -> list[str]:
    try:
        srcs = page.evaluate(
            """() => Array.from(document.querySelectorAll('script[src]'))
                .map(s => s.getAttribute('src') || '')
                .filter(Boolean)""",
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        srcs = []
    if not isinstance(srcs, list):
        srcs = []
    found: list[str] = []
    try:
        inline = page.evaluate(
            """() => Array.from(document.querySelectorAll('script:not([src])'))
                .map(s => s.textContent || '').join('\\n')""",
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        inline = ""
    found.extend(_discover_wishlist_action_ids(inline if isinstance(inline, str) else ""))
    api = request_client
    if api is None:
        # Dedupe what we have from inline scripts only.
        out: list[str] = []
        seen: set[str] = set()
        for aid in found:
            if aid not in seen:
                seen.add(aid)
                out.append(aid)
        return out
    origin = "https://www.humblebundle.com"
    for src in srcs:
        if not isinstance(src, str) or "/_next/" not in src:
            continue
        url = src if src.startswith("http") else f"{origin}{src}" if src.startswith("/") else f"{origin}/{src}"
        try:
            resp = api.get(url, timeout=20_000)
            if int(getattr(resp, "status", 0) or 0) != 200:
                continue
            found.extend(_discover_wishlist_action_ids(resp.text() or ""))
        except Exception:  # noqa: BLE001
            continue
    # Dedupe
    out = []
    seen = set()
    for aid in found:
        if aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def _looks_like_wishlist_payload(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if isinstance(obj.get("wishlist"), list):
        return True
    results = obj.get("results")
    if isinstance(results, list):
        if not results:
            # Successful empty redesigned list (do not treat as "no payload").
            return "pagination" in obj or obj.get("success") is True
        sample = results[0]
        if isinstance(sample, str):
            return True
        if isinstance(sample, dict) and any(
            k in sample
            for k in ("machine_name", "human_name", "human_url", "slug", "title", "product_id")
        ):
            return True
    products = obj.get("products")
    if isinstance(products, list):
        if not products:
            return "pagination" in obj or obj.get("success") is True
        return True
    return False


def _extract_wishlist_payload(text: str) -> dict[str, Any] | None:
    """Pull a wishlist-shaped object out of a Next.js action / RSC body."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if _looks_like_wishlist_payload(obj):
                return obj
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    best: dict[str, Any] | None = None
    best_score = -1
    for key in ("wishlist", "results", "products"):
        for m in re.finditer(rf'"{key}"\s*:\s*\[', text):
            start = text.rfind("{", 0, m.start())
            if start < 0:
                continue
            try:
                obj, _end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                continue
            if not _looks_like_wishlist_payload(obj):
                continue
            score = 0
            for k in ("wishlist", "results", "products"):
                val = obj.get(k)
                if isinstance(val, list):
                    score = max(score, len(val))
            if score >= best_score:
                best = obj
                best_score = score
    return best


def _slugs_from_payload(payload: dict[str, Any]) -> list[str]:
    slugs: list[str] = []
    for key in ("wishlist", "results", "products"):
        val = payload.get(key)
        if not isinstance(val, list):
            continue
        for entry in val:
            if isinstance(entry, str) and entry.strip():
                slugs.append(entry.strip())
            elif isinstance(entry, dict):
                slug = str(
                    entry.get("machine_name")
                    or entry.get("human_url")
                    or entry.get("slug")
                    or entry.get("product_id")
                    or entry.get("id")
                    or ""
                ).strip()
                if slug:
                    slugs.append(slug)
    # Dedupe
    out: list[str] = []
    seen: set[str] = set()
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _rows_from_payload(payload: dict[str, Any]) -> list[dict]:
    for key in ("results", "products", "wishlist"):
        val = payload.get(key)
        if not isinstance(val, list):
            continue
        rows: list[dict] = []
        for entry in val:
            if isinstance(entry, str) and entry.strip():
                rows.append({"machine_name": entry.strip(), "slug": entry.strip()})
            elif isinstance(entry, dict):
                rows.append(entry)
        if rows:
            return rows
    return []


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


def _dom_wishlist_capture(page) -> tuple[bool, list[dict]]:
    """Return ``(ready, rows)`` from a loaded wishlist container only.

    ``ready`` is False while the wishlist root is missing so recommendations /
    nav store links elsewhere on the page cannot poison capture. An empty but
    ready container is a successful empty wishlist.
    """
    raw = page.evaluate(
        """() => {
          const root =
            document.querySelector('[data-testid*="wishlist" i]')
            || document.querySelector('[aria-label*="wishlist" i]')
            || document.querySelector('#wishlist, .wishlist, [class*="wishlist" i]');
          if (!root) return JSON.stringify({ ready: false, rows: [] });
          const skip = new Set([
            'wishlist','cart','search','keys','home','about','support',
            'login','logout','settings','wallet','coupons','choice','monthly'
          ]);
          const out = [];
          const seen = new Set();
          for (const a of root.querySelectorAll('a[href*="/store/"]')) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/\\/store\\/([^/?#]+)/);
            if (!m) continue;
            const slug = decodeURIComponent(m[1]);
            if (!slug || skip.has(slug.toLowerCase()) || seen.has(slug)) continue;
            seen.add(slug);
            const title = (a.getAttribute('title') || a.textContent || '')
              .replace(/\\s+/g, ' ').trim();
            out.push({
              machine_name: slug,
              slug,
              human_url: slug,
              title,
              href: href.startsWith('http') ? href : ('https://www.humblebundle.com' + href),
            });
          }
          return JSON.stringify({ ready: true, rows: out });
        }""",
        timeout=20,
    )
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return False, []
    if not isinstance(payload, dict) or not payload.get("ready"):
        return False, []
    rows = payload.get("rows")
    return True, ([r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else [])


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


def _items_need_lookup(items: list[WishlistItem]) -> bool:
    if not items:
        return False
    return any(not it.price or not it.image_url or it.title == it.product_id for it in items)


def _merge_lookup_into_items(
    row_items: list[WishlistItem],
    looked_up: list[WishlistItem],
) -> list[WishlistItem]:
    """Enrich captured rows with lookup data; keep rows lookup did not return."""
    by_id = {it.product_id: it for it in looked_up}
    merged: list[WishlistItem] = []
    seen: set[str] = set()
    for row in row_items:
        rich = by_id.pop(row.product_id, None)
        seen.add(row.product_id)
        if rich is None:
            merged.append(row)
            continue
        merged.append(
            WishlistItem(
                product_id=row.product_id,
                title=rich.title or row.title,
                image_url=rich.image_url or row.image_url,
                store_url=rich.store_url or row.store_url,
                price=rich.price if rich.price is not None else row.price,
                price_initial=(
                    rich.price_initial if rich.price_initial is not None else row.price_initial
                ),
                discount_percent=(
                    rich.discount_percent
                    if rich.discount_percent is not None
                    else row.discount_percent
                ),
                currency=rich.currency or row.currency,
            )
        )
    for leftover in by_id.values():
        if leftover.product_id not in seen:
            merged.append(leftover)
    return merged


def _fetch_wishlist(*, dump: bool = False) -> tuple[list[WishlistItem], bool]:
    """Return (items, signed_out) from the headed Humble wishlist page."""
    from auth.cdp_browser import STEALTH_INIT_SCRIPT, close_browser_bounded, launch_persistent_profile

    profile = profile_dir("humble")
    if not profile.exists():
        raise RuntimeError(
            "No saved Humble profile at cache/auth/profiles/humble. "
            "Open the Connections page and connect Humble Bundle first."
        )

    captured_payloads: list[dict[str, Any]] = []
    dump_samples: list[dict[str, Any]] = []
    known_actions: set[str] = set()
    if FILTER_WISHLIST_ACTION:
        known_actions.add(FILTER_WISHLIST_ACTION)

    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    )
    try:
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_response(resp) -> None:
            try:
                req = getattr(resp, "request", None)
                headers = {k.lower(): v for k, v in (getattr(req, "headers", None) or {}).items()}
                action = headers.get("next-action") or ""
                url = (getattr(resp, "url", None) or "").lower()
                on_wishlist = "wishlist" in url or "/store/" in url
                if action:
                    if action not in known_actions and not on_wishlist:
                        return
                elif "wishlist" not in url and "lookup" not in url:
                    return
                if int(getattr(resp, "status", 0) or 0) != 200:
                    return
                text = resp.text()
                for aid in _discover_wishlist_action_ids(text):
                    known_actions.add(aid)
                payload = _extract_wishlist_payload(text)
                if payload:
                    if action:
                        known_actions.add(action)
                    captured_payloads.append(payload)
                    if dump:
                        dump_samples.append(
                            {
                                "url": getattr(resp, "url", ""),
                                "next_action": action or None,
                                "payload": payload,
                            }
                        )
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

        # Session probe (same as library); fail fast when clearly anonymous.
        try:
            status_resp = ctx.request.get(SESSION_STATUS_URL, timeout=15_000)
            if status_resp.status == 200:
                body = (status_resp.text() or "").strip()
                if body.startswith("{"):
                    from auth.connect_extractors import humble_session_status_authenticated

                    if not humble_session_status_authenticated(json.loads(body)):
                        return [], True
        except Exception:  # noqa: BLE001
            pass

        page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=60_000)
        for aid in _discover_wishlist_actions_from_page(page, request_client=ctx.request):
            known_actions.add(aid)
            print(f"[humble] wishlist action id discovered: {aid[:12]}…", flush=True)

        slugs: list[str] | None = None
        row_items: list[WishlistItem] = []
        list_resolved = False
        unavailable = False
        deadline = time.time() + _CLEARANCE_WAIT_SEC
        while time.time() < deadline:
            if _page_looks_signed_out(page):
                return [], True
            if _page_shows_wishlist_unavailable(page):
                unavailable = True
                break
            state = _read_wishlist_state(page)
            if state.get("state") == "signed_out":
                return [], True
            if state.get("state") == "ok":
                slugs = [s for s in (state.get("wishlist") or []) if isinstance(s, str)]
                list_resolved = True
                break
            if captured_payloads:
                payload = captured_payloads[-1]
                slugs = _slugs_from_payload(payload)
                row_items = []
                for raw in _rows_from_payload(payload):
                    item = _item_from_wishlist_row(raw)
                    if item:
                        row_items.append(item)
                # Empty redesigned envelope counts as resolved (not auth failure).
                list_resolved = True
                break
            dom_ready, dom_rows = _dom_wishlist_capture(page)
            if dom_ready:
                row_items = []
                for raw in dom_rows:
                    item = _item_from_wishlist_row(raw)
                    if item:
                        row_items.append(item)
                slugs = [r["machine_name"] for r in dom_rows if r.get("machine_name")]
                list_resolved = True
                break
            page.wait_for_timeout(1000)

        if unavailable:
            if dump:
                dump_json().parent.mkdir(parents=True, exist_ok=True)
                dump_json().write_text(
                    json.dumps(
                        {
                            "unavailable": True,
                            "url": getattr(page, "url", None),
                            "markers": list(_WISHLIST_UNAVAILABLE_MARKERS),
                            "captured": dump_samples[:10],
                            "known_actions": sorted(known_actions),
                        },
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                print(f"  wrote {dump_json()}", flush=True)
            raise WishlistUnavailableError(
                "Humble wishlist is temporarily unavailable "
                "(\"Wishlist Will Be Back ASAP\" interstitial during site upgrades). "
                "Library sync is unaffected; retry wishlist after Humble restores it."
            )

        if not list_resolved and slugs is None and not row_items:
            if _page_looks_signed_out(page):
                return [], True
            raise RuntimeError(
                "Humble wishlist did not expose a list payload "
                "(no user_json, no Next action results, no wishlist DOM rows)."
            )

        # Prefer rich row items; enrich via lookup when prices/images are missing.
        lookup_results: list[dict] = []
        if row_items and not _items_need_lookup(row_items):
            items = row_items
        else:
            lookup_slugs = slugs if slugs is not None else [it.product_id for it in row_items]
            lookup_results = _lookup_products(page, lookup_slugs) if lookup_slugs else []
            looked_up = [it for it in (_item_from_lookup(o) for o in lookup_results) if it]
            if row_items:
                items = _merge_lookup_into_items(row_items, looked_up)
            else:
                # Legacy slug-only path: lookup is the sole source of rows.
                items = looked_up

        if dump:
            dump_json().parent.mkdir(parents=True, exist_ok=True)
            dump_json().write_text(
                json.dumps(
                    {
                        "slug_count": len(slugs or []),
                        "slugs": slugs or [it.product_id for it in items],
                        "result_count": len(lookup_results),
                        "results": lookup_results[:20],
                        "captured": dump_samples[:10],
                        "known_actions": sorted(known_actions),
                        "row_item_count": len(row_items),
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
    except WishlistUnavailableError as exc:
        # Humble-side outage during redesign — do not invalidate the shared login.
        stats.error(str(exc))
        return stats.finish("fetch_humble_wishlist", t0, exit_code=2, extra="wishlist unavailable")
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
