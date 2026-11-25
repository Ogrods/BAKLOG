#!/usr/bin/env python3
"""Fetch Humble Bundle library into games_humble.json.

Uses the saved Humble browser profile (Connections -> Humble Bundle).

After Humble's Nov 2026 redesign the legacy JSON endpoints
(``/api/v1/user/order``, ``/api/v1/order/{gamekey}``) return 404. The site
library at ``/home/library`` loads via a Next.js server action
(``filterUserLibrary``). This fetcher lands on that page in a headed
off-screen Chrome, discovers the live action id, then pages the library with
in-page ``fetch`` (limit=100) so Cloudflare clearance and cookies stay in the
real browser. No response-body sniffing.

Emits games-only rows by default (drops ebooks, comics, audiobooks, software).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid
from auth.secrets import profile_dir
from clients.hltb_client import HltbClient
from fetchers._authoritative import HUMBLE
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    add_only_new_arg,
    apply_carry_forward,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    refuse_drift_result,
    refuse_empty_result,
    row_key_by_id,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, HeartbeatTimer, RunStats, run_with_heartbeat, started
from fetchers.humble_library_api import (
    EMPTY_LIBRARY_ACTION_STATE,
    FILTER_USER_LIBRARY_ACTION,
    LIBRARY_URL,
    LibraryItem,
    discover_action_id,
    extract_bundle_items,
    extract_library_page,
    item_from_result,
    library_action_form_fields,
    library_result_is_game,
    match_cached_row,
    norm_title_key,
    order_entitlements,
    rsc_headers,
    steam_app_from_library_result,
)

GAMES_HUMBLE_JSON = Path("games_humble.json")
# Re-export for tests / callers that still import from this module.
_FILTER_USER_LIBRARY_ACTION_RE = re.compile(
    r"""["']([a-f0-9]{40,44})["'].{0,160}?filterUserLibrary""",
    re.DOTALL,
)
# Legacy endpoints (kept for dump/docs; redesign returns 404 HTML).
ORDERS_URL = "https://www.humblebundle.com/api/v1/user/order"
ORDER_DETAIL_URL = "https://www.humblebundle.com/api/v1/order/{gamekey}?all_tpkds=true"
SESSION_STATUS_URL = "https://www.humblebundle.com/api/auth/session-status"

_LIB_WINDOW_POS = (-32000, 0)
_LIB_WINDOW_SIZE = (1280, 900)
_CLEARANCE_WAIT_SEC = 90
_ACTION_PAGE_LIMIT = 100
_ACTION_PAGE_DELAY_SEC = 0.35
_CHROME_STUCK_MSG = (
    "Humble page did not load; close other BAKLOG browser windows and retry"
)

HLTB_DELAY_SEC = 1.0

_GAME_PLATFORMS = frozenset({"windows", "mac", "linux", "android"})
_GAME_KEY_TYPES = frozenset({
    "steam", "origin", "uplay", "ubisoft", "epic", "gog", "battlenet", "external",
})
_NONGAME_KEY_TYPES = frozenset({
    "ebook", "audiobook", "comic", "software", "soundtrack", "asmjs", "video",
})


def dump_path() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "humble" / "library_dump.json"


# --- Legacy order parsers (fixture / docs; not used by the live fetch path) ---


def _tpk_ids_for_sub(sub: dict) -> list[str]:
    tpks = sub.get("tpks") or {}
    if isinstance(tpks, dict):
        out: list[str] = []
        for v in tpks.values():
            if isinstance(v, list):
                out.extend(str(x) for x in v)
            elif isinstance(v, str):
                out.append(v)
        return out
    if isinstance(tpks, list):
        return [str(x) for x in tpks]
    return []


def _subproduct_is_game(sub: dict, tpkd_dict: dict) -> bool:
    downloads = sub.get("downloads") or []
    if isinstance(downloads, list):
        for dl in downloads:
            if not isinstance(dl, dict):
                continue
            plat = (dl.get("platform") or "").lower()
            if plat in _GAME_PLATFORMS:
                return True
    for tid in _tpk_ids_for_sub(sub):
        tpkd = tpkd_dict.get(tid) if isinstance(tpkd_dict, dict) else None
        if not isinstance(tpkd, dict):
            continue
        kt = (tpkd.get("key_type") or "").lower()
        if kt in _NONGAME_KEY_TYPES:
            continue
        if kt in _GAME_KEY_TYPES or kt == "steam":
            return True
    human = (sub.get("human_name") or "").lower()
    if any(tok in human for tok in ("soundtrack only", "ebook", "audiobook", "comic book")):
        return False
    return False


def _steam_app_from_sub(sub: dict, tpkd_dict: dict) -> str | None:
    for tid in _tpk_ids_for_sub(sub):
        tpkd = tpkd_dict.get(tid) if isinstance(tpkd_dict, dict) else None
        if not isinstance(tpkd, dict):
            continue
        if (tpkd.get("key_type") or "").lower() != "steam":
            continue
        for field in ("steam_app_id", "steam_appid", "steam_id"):
            val = tpkd.get(field)
            if val is not None:
                return str(val)
        m = re.search(r"steam.*?(\d{4,8})", str(tpkd.get("custom_instructions") or ""), re.I)
        if m:
            return m.group(1)
    return None


def _store_url(machine_name: str, steam_app_id: str | None) -> str:
    if steam_app_id:
        return f"https://store.steampowered.com/app/{steam_app_id}"
    slug = quote(machine_name or "", safe="")
    return f"https://www.humblebundle.com/store/{slug}" if slug else "https://www.humblebundle.com/store"


def _parse_order_detail(data: dict, *, include_nongames: bool) -> list[LibraryItem]:
    gamekey = str(data.get("gamekey") or "")
    tpkd_dict = data.get("tpkd_dict") or {}
    if not isinstance(tpkd_dict, dict):
        tpkd_dict = {}
    items: list[LibraryItem] = []
    seen: set[str] = set()
    for sub in data.get("subproducts") or []:
        if not isinstance(sub, dict):
            continue
        if not include_nongames and not _subproduct_is_game(sub, tpkd_dict):
            continue
        machine = str(sub.get("machine_name") or sub.get("custom_download_page_name") or "").strip()
        name = str(sub.get("human_name") or machine or "").strip()
        if not machine and not name:
            continue
        row_id = machine or name
        if row_id in seen:
            continue
        seen.add(row_id)
        icon = sub.get("icon") or sub.get("image")
        image = icon if isinstance(icon, str) and icon.startswith("http") else None
        steam_id = _steam_app_from_sub(sub, tpkd_dict)
        redeemed = sub.get("redeemed")
        if redeemed is None and steam_id:
            redeemed = False
        items.append(
            LibraryItem(
                machine_name=machine or row_id,
                name=name or machine,
                image_url=image,
                store_url=_store_url(machine, steam_id),
                gamekey=gamekey,
                redeemed=redeemed if isinstance(redeemed, bool) else None,
                steam_app_id=steam_id,
            )
        )
    return items


# --- Thin wrappers kept so existing tests can import from this module ---


def _discover_filter_user_library_action(text: str) -> str | None:
    return discover_action_id(text)


def _looks_like_filter_user_library_payload(obj: Any) -> bool:
    from fetchers.humble_library_api import looks_like_filter_user_library_payload

    return looks_like_filter_user_library_payload(obj)


def _extract_filter_user_library_payload(text: str) -> dict[str, Any] | None:
    return extract_library_page(text)


def _library_result_is_game(obj: dict) -> bool:
    return library_result_is_game(obj)


def _steam_app_from_library_result(obj: dict) -> str | None:
    return steam_app_from_library_result(obj)


def _item_from_library_result(obj: dict, *, include_nongames: bool) -> LibraryItem | None:
    return item_from_result(obj, include_nongames=include_nongames)


# --- Page / auth helpers ---


def _page_html_snippet(page) -> str:
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        return ""
    return (html or "")[:4000].lower()


def _page_on_cloudflare(page) -> bool:
    html = _page_html_snippet(page)
    return "cf-browser-verification" in html or "just a moment" in html or "challenge-platform" in html


def _page_looks_signed_out(page) -> bool:
    from auth.connect_extractors import humble_page_title_looks_login

    url = (_page_url_hint(page) or "").lower()
    if "auth.humblebundle.com" in url:
        return True
    if "/login" in url and "humblebundle.com" in url:
        return True
    try:
        title = page.title() if hasattr(page, "title") else ""
    except Exception:  # noqa: BLE001
        title = ""
    if humble_page_title_looks_login(title or ""):
        return True
    return False


def _session_expired_message(page) -> str:
    url = _page_url_hint(page)
    return f"Humble session expired (url={url!r})"


def _page_url_hint(page) -> str:
    url = (getattr(page, "url", None) or "").strip()
    if url and url not in ("about:blank", "") and not url.startswith("chrome://"):
        return url
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return url
    try:
        href = evaluate("() => location.href", timeout=2)
        if isinstance(href, str) and href.strip():
            return href.strip()
    except Exception:  # noqa: BLE001
        pass
    return url


def _tab_is_chrome_internal(url: str) -> bool:
    u = (url or "").strip().lower()
    return not u or u == "about:blank" or u.startswith("chrome://")


def _page_is_humble_library(page) -> bool:
    from auth.connect_extractors import humble_page_is_confirmed_library_or_store

    url = _page_url_hint(page)
    if humble_page_is_confirmed_library_or_store(url):
        return True
    return "humblebundle.com/home/library" in (url or "").lower()


def _pick_humble_library_page(ctx):
    """Prefer an existing Humble library tab; skip chrome:// NTP when possible."""
    pages = [p for p in (getattr(ctx, "pages", None) or []) if not getattr(p, "is_closed", False)]
    for page in pages:
        if _page_is_humble_library(page):
            return page
    for page in pages:
        if not _tab_is_chrome_internal(_page_url_hint(page)):
            return page
    if pages:
        return pages[0]
    return ctx.new_page()


def _humble_main_auth_failure(msg: str) -> bool:
    low = msg.lower()
    if "expired" in low or "401" in msg or "403" in msg:
        return True
    if msg.startswith("Humble session expired"):
        return True
    if "auth.humblebundle.com" in low:
        return True
    from auth.url_hosts import host_matches

    for token in re.findall(r"https?://[^\s'\"]+", msg):
        if host_matches(token, "auth.humblebundle.com"):
            return True
    return False


def _goto_humble_library(page, ctx):
    """Navigate to /home/library; retry once on a fresh tab if CDP navigate fails."""
    last_exc: Exception | None = None
    current = page
    chrome_stuck = False
    for attempt in range(2):
        if _page_is_humble_library(current):
            return current
        if _tab_is_chrome_internal(_page_url_hint(current)):
            if attempt == 0:
                try:
                    current = ctx.new_page()
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    break
        try:
            current.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=30_000)
            if _page_is_humble_library(current):
                return current
            url = _page_url_hint(current).lower()
            if _tab_is_chrome_internal(url):
                chrome_stuck = True
                last_exc = RuntimeError(_CHROME_STUCK_MSG)
            else:
                return current
        except Exception as exc:  # noqa: BLE001
            if _page_is_humble_library(current):
                return current
            last_exc = exc
            if attempt == 0:
                print(
                    f"[humble] library navigate failed ({exc}); retrying on a new tab",
                    flush=True,
                )
                try:
                    current = ctx.new_page()
                except Exception as new_exc:  # noqa: BLE001
                    last_exc = new_exc
                    break
    if chrome_stuck:
        raise RuntimeError(_CHROME_STUCK_MSG)
    if last_exc:
        raise last_exc
    raise RuntimeError(_CHROME_STUCK_MSG)


def _page_evaluate_alive(page) -> bool:
    """True when Runtime.evaluate works on this CDP session."""
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return False
    try:
        val = evaluate("() => 1", timeout=5)
        return val == 1
    except Exception:  # noqa: BLE001
        return False


def _rebind_live_library_page(ctx, page):
    """Prefer a library tab whose CDP session still accepts evaluate."""
    candidates = []
    if page is not None and not getattr(page, "is_closed", False):
        candidates.append(page)
    for p in list(getattr(ctx, "pages", None) or []):
        if p is page or getattr(p, "is_closed", False):
            continue
        candidates.append(p)
    library_alive = [
        p for p in candidates if _page_is_humble_library(p) and _page_evaluate_alive(p)
    ]
    if library_alive:
        return library_alive[0]
    alive = [p for p in candidates if _page_evaluate_alive(p)]
    if alive:
        return alive[0]
    # Last resort: new tab (caller will navigate again if needed).
    try:
        return ctx.new_page()
    except Exception:  # noqa: BLE001
        return page


def _wait_library_ready(page) -> None:
    deadline = time.time() + _CLEARANCE_WAIT_SEC
    cf_logged = False
    while time.time() < deadline:
        if _page_on_cloudflare(page):
            if not cf_logged:
                print(
                    "[humble] Cloudflare challenge on library; waiting for clearance",
                    flush=True,
                )
                cf_logged = True
            page.wait_for_timeout(1000)
            continue
        if _page_looks_signed_out(page):
            raise RuntimeError(_session_expired_message(page))
        if _page_is_humble_library(page):
            return
        page.wait_for_timeout(500)
    if _page_on_cloudflare(page):
        raise RuntimeError(
            f"Humble library blocked by Cloudflare (url={_page_url_hint(page)!r})"
        )
    if _page_looks_signed_out(page):
        raise RuntimeError(_session_expired_message(page))


def _discover_action_id_on_page(page) -> str | None:
    """Scan inline scripts + linked chunks for the live filterUserLibrary id."""
    try:
        found = page.evaluate(
            """async () => {
              const re = /["']([a-f0-9]{40,44})["'].{0,160}?filterUserLibrary/s;
              const inline = Array.from(document.querySelectorAll('script:not([src])'))
                .map(s => s.textContent || '').join('\\n');
              let m = inline.match(re);
              if (m) return m[1];
              const srcs = Array.from(document.querySelectorAll('script[src]'))
                .map(s => s.src || '')
                .filter(s => s.includes('/_next/'));
              for (const src of srcs) {
                try {
                  const t = await (await fetch(src)).text();
                  m = t.match(re);
                  if (m) return m[1];
                } catch (e) {}
              }
              return null;
            }""",
            timeout=60,
        )
    except Exception:  # noqa: BLE001
        return None
    return found if isinstance(found, str) and found else None


def _in_page_library_action(
    page,
    *,
    action_id: str,
    page_num: int,
    limit: int,
    cursor: int,
) -> dict[str, Any]:
    """POST filterUserLibrary via in-page fetch; returns status + body text."""
    fields = library_action_form_fields(
        page=page_num,
        limit=limit,
        cursor=cursor,
        request_id=f"bk{page_num}",
        prev_state=EMPTY_LIBRARY_ACTION_STATE,
    )
    # Build the router tree in-page with encodeURIComponent (matches the live
    # site / Cursor-tab probe that honors limit=100). Pre-quoted Python headers
    # were ignored by Humble and always returned page 1 / limit 5.
    tree_json = json.dumps(
        [
            "",
            {
                "children": [
                    "(default)",
                    {
                        "children": [
                            "(account)",
                            {
                                "children": [
                                    "home",
                                    {
                                        "children": [
                                            "library",
                                            {
                                                "children": [
                                                    "__PAGE__",
                                                    {},
                                                    None,
                                                    None,
                                                    0,
                                                ]
                                            },
                                            None,
                                            None,
                                            4,
                                        ]
                                    },
                                    None,
                                    None,
                                    8,
                                ]
                            },
                            None,
                            None,
                            8,
                        ]
                    },
                    None,
                    None,
                    24,
                ]
            },
            None,
            None,
            True,
        ]
    )
    args_json = json.dumps(
        {"fields": fields, "actionId": action_id, "treeJson": tree_json}
    )
    result = page.evaluate(
        f"""async () => {{
          const args = {args_json};
          const fd = new FormData();
          for (const [k, v] of Object.entries(args.fields)) fd.append(k, String(v));
          const r = await fetch('/home/library', {{
            method: 'POST',
            headers: {{
              'Accept': 'text/x-component',
              'Next-Action': args.actionId,
              'Next-Router-State-Tree': encodeURIComponent(args.treeJson),
            }},
            body: fd,
            credentials: 'include',
          }});
          const text = await r.text();
          return {{
            status: r.status,
            url: r.url || '',
            ct: r.headers.get('content-type') || '',
            text,
          }};
        }}""",
        timeout=60,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Humble library action returned no result")
    return result


def _in_page_rsc_get(page, path: str) -> dict[str, Any]:
    args_json = json.dumps({"path": path, "headers": rsc_headers()})
    result = page.evaluate(
        f"""async () => {{
          const args = {args_json};
          const r = await fetch(args.path, {{
            method: 'GET',
            headers: args.headers,
            credentials: 'include',
          }});
          const text = await r.text();
          return {{ status: r.status, url: r.url || '', text }};
        }}""",
        timeout=60,
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"Humble RSC GET {path} returned no result")
    return result


def _raise_if_auth_status(status: int, page) -> None:
    if status in (401, 403):
        raise RuntimeError(_session_expired_message(page))


def _fetch_via_action(
    page,
    *,
    action_id: str,
    include_nongames: bool,
    dump_samples: list[dict[str, Any]] | None,
) -> list[LibraryItem]:
    found: dict[str, LibraryItem] = {}
    page_num = 1
    total_pages = 1
    cursor = 0
    stall_count = 0
    while page_num <= max(total_pages, 1) and page_num <= 500:
        print(
            f"[library action page {page_num}] limit={_ACTION_PAGE_LIMIT} cursor={cursor}",
            flush=True,
        )
        raw = _in_page_library_action(
            page,
            action_id=action_id,
            page_num=page_num,
            limit=_ACTION_PAGE_LIMIT,
            cursor=cursor,
        )
        status = int(raw.get("status") or 0)
        _raise_if_auth_status(status, page)
        text = str(raw.get("text") or "")
        if status >= 400:
            raise RuntimeError(f"Humble library action HTTP {status}")
        payload = extract_library_page(text)
        if not payload:
            if page_num == 1:
                return []
            break
        if dump_samples is not None and len(dump_samples) < 5:
            dump_samples.append(
                {
                    "via": "filterUserLibrary",
                    "page": page_num,
                    "status": status,
                    "payload": _scrub_payload_for_dump(payload),
                }
            )
        pag = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        payload_page = int(pag.get("page") or 0) or page_num
        total_pages = max(total_pages, int(pag.get("totalPages") or 1) or 1)
        total_docs = int(pag.get("totalDocs") or 0)
        results = [r for r in (payload.get("results") or []) if isinstance(r, dict)]
        page_items = 0
        new_items = 0
        for row in results:
            item = item_from_result(row, include_nongames=include_nongames)
            if not item:
                continue
            page_items += 1
            if item.machine_name not in found:
                found[item.machine_name] = item
                new_items += 1
        print(
            f"  page {page_num}: {page_items} rows ({new_items} new), "
            f"payloadPage={payload_page} totalPages={total_pages} "
            f"totalDocs~{total_docs} collected={len(found)}",
            flush=True,
        )
        # Humble sometimes ignores our limit/cursor and keeps returning page 1.
        if payload_page != page_num or (page_num > 1 and new_items == 0):
            stall_count += 1
        else:
            stall_count = 0
        if stall_count >= 1 and page_num == 1 and total_pages > 1 and len(results) < total_docs:
            print(
                "[humble] filterUserLibrary ignored page/limit; falling back to RSC orders",
                flush=True,
            )
            return []
        if stall_count >= 2:
            print(
                "[humble] filterUserLibrary pagination stalled; falling back to RSC orders",
                flush=True,
            )
            return []
        if page_num >= total_pages:
            break
        # Advance cursor by the effective page size Humble actually returned.
        effective_limit = len(results) or _ACTION_PAGE_LIMIT
        cursor = page_num * effective_limit
        page_num += 1
        time.sleep(_ACTION_PAGE_DELAY_SEC)
    return list(found.values())


def _scrub_payload_for_dump(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop secrets from dump samples (keys, user ids)."""
    try:
        blob = json.dumps(payload)
    except (TypeError, ValueError):
        return {"results": [], "note": "unserializable"}
    blob = re.sub(r'"keyFormatted"\s*:\s*"[^"]*"', '"keyFormatted":"<redacted>"', blob)
    blob = re.sub(r'"userId"\s*:\s*"[^"]*"', '"userId":"<redacted>"', blob)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return {"results": [], "note": "scrub-failed"}


def _fetch_via_rsc_orders(
    page,
    *,
    include_nongames: bool,
    dump_samples: list[dict[str, Any]] | None,
) -> list[LibraryItem]:
    """Fallback: RSC order list + per-order entitlement pages."""
    print("[humble] filterUserLibrary empty/failed; trying RSC order list", flush=True)
    listing = _in_page_rsc_get(page, "/home/library")
    _raise_if_auth_status(int(listing.get("status") or 0), page)
    orders = extract_bundle_items(str(listing.get("text") or ""))
    if not orders:
        return []
    if dump_samples is not None and len(dump_samples) < 5:
        dump_samples.append(
            {
                "via": "rsc_library",
                "order_count": len(orders),
                "order_ids": [str(o.get("id") or "")[:36] for o in orders[:10]],
            }
        )
    found: dict[str, LibraryItem] = {}
    for i, order in enumerate(orders, 1):
        order_id = str(order.get("id") or "").strip()
        if not order_id:
            continue
        print(f"[rsc order {i}/{len(orders)}] {order_id[:8]}…", flush=True)
        detail = _in_page_rsc_get(page, f"/home/library/{order_id}")
        status = int(detail.get("status") or 0)
        _raise_if_auth_status(status, page)
        if status >= 400:
            print(f"  skip order HTTP {status}", flush=True)
            continue
        ents = order_entitlements(str(detail.get("text") or ""))
        # If the order page itself is a single content-entitlement, include it.
        if not ents and order.get("itemType") == "content-entitlement":
            ents = [order]
        for row in ents:
            item = item_from_result(row, include_nongames=include_nongames)
            if item and item.machine_name not in found:
                found[item.machine_name] = item
        time.sleep(_ACTION_PAGE_DELAY_SEC)
    return list(found.values())


def fetch_library_items(
    *,
    include_nongames: bool = False,
    dump: bool = False,
) -> list[LibraryItem]:
    """Fetch all library items using the saved Humble profile (redesign UI path)."""
    from auth.cdp_browser import close_browser_bounded, launch_persistent_profile

    profile = profile_dir("humble")
    if not profile.exists():
        raise RuntimeError(
            "No saved Humble profile at cache/auth/profiles/humble. "
            "Open the Connections page and connect Humble Bundle first."
        )

    dump_samples: list[dict[str, Any]] = []

    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_LIB_WINDOW_POS,
        window_size=_LIB_WINDOW_SIZE,
    )
    try:
        try:
            from auth.connect_extractors import restore_humble_session_cookies

            restored = restore_humble_session_cookies(ctx, profile)
            if restored:
                print(f"[humble] restored {restored} cookie(s) from Connect sidecar", flush=True)
        except Exception:  # noqa: BLE001
            pass

        page = _pick_humble_library_page(ctx)

        # Soft diagnostic only — cold cookies often look anonymous until library loads.
        try:
            status_resp = ctx.request.get(SESSION_STATUS_URL, timeout=15_000)
            if status_resp.status == 200:
                body = (status_resp.text() or "").strip()
                if body.startswith("{"):
                    from auth.connect_extractors import humble_session_status_authenticated

                    if not humble_session_status_authenticated(json.loads(body)):
                        print(
                            "[humble] session-status anonymous before navigate; "
                            "continuing to library",
                            flush=True,
                        )
        except Exception:  # noqa: BLE001
            pass

        page = _goto_humble_library(page, ctx)
        try:
            page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            pass
        # OneTrust / consent overlays block library hydration in a fresh profile.
        try:
            page.evaluate(
                """() => {
                  for (const label of ['I Consent', 'Accept All', 'Accept', 'Got it']) {
                    const btn = Array.from(document.querySelectorAll('button'))
                      .find(b => (b.textContent || '').trim() === label);
                    if (btn) { btn.click(); return label; }
                  }
                  return null;
                }""",
                timeout=5,
            )
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            pass
        page = _rebind_live_library_page(ctx, page)
        if not _page_is_humble_library(page):
            page = _goto_humble_library(page, ctx)
            page = _rebind_live_library_page(ctx, page)
        if not _page_on_cloudflare(page) and _page_looks_signed_out(page):
            raise RuntimeError(_session_expired_message(page))
        _wait_library_ready(page)
        page = _rebind_live_library_page(ctx, page)
        if not _page_evaluate_alive(page):
            raise RuntimeError(
                "Humble library tab lost its browser session; close other BAKLOG "
                "browser windows and retry"
            )

        action_id = _discover_action_id_on_page(page) or FILTER_USER_LIBRARY_ACTION
        if action_id != FILTER_USER_LIBRARY_ACTION:
            print(f"[humble] filterUserLibrary action id updated: {action_id[:12]}…", flush=True)
        else:
            print(f"[humble] using filterUserLibrary action {action_id[:12]}…", flush=True)

        try:
            items = _fetch_via_action(
                page,
                action_id=action_id,
                include_nongames=include_nongames,
                dump_samples=dump_samples if dump else None,
            )
        except Exception as exc:  # noqa: BLE001
            if "Session with given id not found" not in str(exc):
                raise
            print(
                "[humble] CDP session dropped mid-fetch; rebinding library tab and retrying",
                flush=True,
            )
            page = _rebind_live_library_page(ctx, page)
            if not _page_is_humble_library(page) or not _page_evaluate_alive(page):
                page = _goto_humble_library(page, ctx)
                page = _rebind_live_library_page(ctx, page)
            items = _fetch_via_action(
                page,
                action_id=action_id,
                include_nongames=include_nongames,
                dump_samples=dump_samples if dump else None,
            )
        if not items:
            items = _fetch_via_rsc_orders(
                page,
                include_nongames=include_nongames,
                dump_samples=dump_samples if dump else None,
            )

        if dump:
            dump_path().parent.mkdir(parents=True, exist_ok=True)
            dump_path().write_text(
                json.dumps(
                    {
                        "action_id": action_id,
                        "item_count": len(items),
                        "samples": dump_samples,
                        "items": [
                            {
                                "machine_name": it.machine_name,
                                "name": it.name,
                                "store_url": it.store_url,
                                "gamekey": it.gamekey,
                                "redeemed": it.redeemed,
                                "delivery_type": it.delivery_type,
                            }
                            for it in list(items)[:40]
                        ],
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"  wrote {dump_path()}", flush=True)
            return []

        if not items:
            raise RuntimeError(
                "Humble library page returned no items (redesign UI empty or blocked)"
            )
        return sorted(items, key=lambda x: x.name.lower())
    finally:
        close_browser_bounded(ctx, profile=profile)


def _build_row(item: LibraryItem, hltb: dict | None) -> dict:
    tags: list[str] = []
    if item.redeemed is False:
        tags.append("unredeemed key")
    if item.expired:
        tags.append("expired key")
    if item.steam_app_id or (item.delivery_type or "").lower() == "steam":
        tags.append("Steam key")

    return {
        "store": "humble",
        "id": f"humble-{item.machine_name}",
        "humble_id": item.machine_name,
        "humble_gamekey": item.gamekey,
        "humble_steam_app_id": item.steam_app_id,
        "name": item.name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": item.image_url,
        "library_image": item.image_url,
        "release_date": None,
        "genres": [],
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
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }


def _load_existing_indexes() -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (by_humble_id, by_norm_title) for cache continuity."""
    if not catalog_file(GAMES_HUMBLE_JSON).exists():
        return {}, {}
    try:
        data = json.loads(catalog_file(GAMES_HUMBLE_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}
    by_id: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    for g in data.get("games", []):
        if not isinstance(g, dict):
            continue
        hid = g.get("humble_id")
        if hid:
            by_id[str(hid)] = g
        tk = norm_title_key(str(g.get("name") or ""))
        if tk and tk not in by_title:
            by_title[tk] = g
    return by_id, by_title


def _load_existing_by_machine() -> dict[str, dict]:
    by_id, _by_title = _load_existing_indexes()
    return by_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Humble library into games_humble.json")
    parser.add_argument(
        "--skip-hltb",
        action="store_true",
        help="Accepted for manifest/dashboard parity; HLTB is off by default (use --hltb to enable)",
    )
    add_only_new_arg(parser)
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    parser.add_argument(
        "--include-nongames",
        action="store_true",
        help="Include ebooks, comics, audiobooks, and software (default is games only)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help=f"Save sample API payloads to {dump_path()} and exit",
    )
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_humble")
    stats = RunStats()
    load_dotenv()

    print("Fetching Humble library via /home/library...", flush=True)
    try:
        items = run_with_heartbeat(
            lambda: fetch_library_items(include_nongames=args.include_nongames, dump=args.dump),
            "Humble library page",
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if _humble_main_auth_failure(msg):
            mark_invalid("humble", error=msg)
            stats.error(msg)
            return stats.finish("fetch_humble", t0, exit_code=EXIT_CODE_AUTH)
        stats.error(msg)
        return stats.finish("fetch_humble", t0, exit_code=1)

    if args.dump:
        return stats.finish("fetch_humble", t0, exit_code=0, extra="dump only")

    print(f"  parsed {len(items)} library items", flush=True)

    empty_exit = refuse_empty_result(
        items,
        label="Humble library",
        allow_empty=args.allow_empty,
        output_path=GAMES_HUMBLE_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_humble", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="Humble library",
        allow_drift=args.allow_drift,
        output_path=GAMES_HUMBLE_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_humble", t0, exit_code=drift_exit)

    hltb_client = HltbClient() if args.hltb else None
    by_id, by_title = _load_existing_indexes()
    rows: list[dict] = []
    loop_hb = HeartbeatTimer(interval=25.0)
    for i, item in enumerate(items, 1):
        cached = match_cached_row(item, by_id, by_title)
        if args.only_new and cached:
            rows.append(cached)
            loop_hb.tick_progress(i, len(items), "Humble library", "cached")
            continue
        print(f"[{i}/{len(items)}] {item.name}", flush=True)
        loop_hb.reset()
        hltb = None
        hltb_updated = False
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
                    hltb_updated = bool(hltb)
                except Exception as exc:  # noqa: BLE001
                    print(f"  HLTB warning: {exc}", flush=True)
        rows.append(
            merge_cached_row(
                _build_row(item, hltb),
                cached,
                authoritative=HUMBLE,
                hltb_updated=hltb_updated,
            )
        )
        loop_hb.tick_progress(i, len(items), "Humble library", item.name[:40])

    rows = apply_carry_forward(
        rows,
        by_id,
        key_fn=row_key_by_id,
        no_carry=args.no_carry,
    )

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "humble",
        "game_count": len(rows),
        "games": rows,
    }
    write_catalog_text(GAMES_HUMBLE_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(rows)} games to {GAMES_HUMBLE_JSON}.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_humble", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    sys.exit(main())
