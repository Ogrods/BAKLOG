#!/usr/bin/env python3
"""Fetch Humble Bundle library into games_humble.json.

Uses the saved Humble browser profile (Connections -> Humble Bundle).

After Humble's Nov 2026 redesign the legacy JSON endpoints
(``/api/v1/user/order``, ``/api/v1/order/{gamekey}``) return 404. The site
library at ``/home/library`` loads via a Next.js server action
(``filterUserLibrary``). This fetcher drives that page in a headed off-screen
Chrome (same Cloudflare approach as the Humble wishlist fetcher), captures
action payloads and/or DOM rows, and paginates until exhausted.

Emits games-only rows by default (drops ebooks, comics, audiobooks, software).
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

GAMES_HUMBLE_JSON = Path("games_humble.json")
LIBRARY_URL = "https://www.humblebundle.com/home/library"
# Next.js server action id for filterUserLibrary (from /home/library client bundle).
FILTER_USER_LIBRARY_ACTION = "60199147c9d010842d98602b018a506278c5317f8e"
# Legacy endpoints (kept for dump/fallback; redesign returns 404 HTML).
ORDERS_URL = "https://www.humblebundle.com/api/v1/user/order"
ORDER_DETAIL_URL = "https://www.humblebundle.com/api/v1/order/{gamekey}?all_tpkds=true"
SESSION_STATUS_URL = "https://www.humblebundle.com/api/auth/session-status"

# Headed but off-screen: same real-browser fingerprint as Connect / wishlist.
_LIB_WINDOW_POS = (-32000, 0)
_LIB_WINDOW_SIZE = (1280, 900)
_CLEARANCE_WAIT_SEC = 45
_PAGE_LIMIT = 5
_PAGE_DELAY_SEC = 0.6


def dump_path() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "humble" / "library_dump.json"


HLTB_DELAY_SEC = 1.0
ORDER_DELAY_SEC = 0.35

_GAME_PLATFORMS = frozenset({"windows", "mac", "linux", "android"})
_GAME_KEY_TYPES = frozenset({
    "steam", "origin", "uplay", "ubisoft", "epic", "gog", "battlenet", "external",
})
_NONGAME_KEY_TYPES = frozenset({
    "ebook", "audiobook", "comic", "software", "soundtrack", "asmjs", "video",
})
_NONGAME_PRODUCT_TYPES = frozenset({
    "ebook", "audiobook", "comic", "software", "soundtrack", "asmjs", "video",
})


@dataclass
class LibraryItem:
    machine_name: str
    name: str
    image_url: str | None
    store_url: str
    gamekey: str
    redeemed: bool | None
    steam_app_id: str | None


def _api_get(ctx, url: str, *, timeout_ms: int = 45_000) -> Any:
    resp = ctx.request.get(url, timeout=timeout_ms)
    if resp.status >= 400:
        raise RuntimeError(f"Humble API {url} returned HTTP {resp.status}")
    return json.loads(resp.text())


def _signed_out(exc: Exception | None = None) -> bool:
    if exc is None:
        return False
    msg = str(exc).lower()
    return "401" in msg or "403" in msg or "sign in" in msg


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


def _extract_filter_user_library_payload(text: str) -> dict[str, Any] | None:
    """Pull ``{results, pagination, success}`` out of a Next.js action / RSC body."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{") and '"results"' in stripped:
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and isinstance(obj.get("results"), list):
                return obj
        except json.JSONDecodeError:
            pass
    # Flight / RSC bodies embed JSON objects; take the richest results blob.
    best: dict[str, Any] | None = None
    for m in re.finditer(r"\"results\"\s*:\s*\[", text):
        start = text.rfind("{", 0, m.start())
        if start < 0:
            continue
        depth = 0
        end = None
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue
        try:
            obj = json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("results"), list):
            if best is None or len(obj["results"]) >= len(best.get("results") or []):
                best = obj
    return best


def _library_result_is_game(obj: dict) -> bool:
    product_type = str(obj.get("productType") or obj.get("type") or "").strip().lower()
    if product_type in _NONGAME_PRODUCT_TYPES:
        return False
    title = str(obj.get("title") or obj.get("human_name") or "").lower()
    if any(tok in title for tok in ("soundtrack only", "ebook", "audiobook", "comic book")):
        return False
    return True


def _steam_app_from_library_result(obj: dict) -> str | None:
    ents = obj.get("entitlements") if isinstance(obj.get("entitlements"), dict) else {}
    for key in ("keys", "downloads"):
        for ent in ents.get(key) or []:
            if not isinstance(ent, dict):
                continue
            for field in ("steam_app_id", "steam_appid", "steamAppId"):
                val = ent.get(field)
                if val is not None and str(val).strip():
                    return str(val).strip()
    return None


def _item_from_library_result(obj: dict, *, include_nongames: bool) -> LibraryItem | None:
    """Map one filterUserLibrary / DOM row into a LibraryItem."""
    if not isinstance(obj, dict):
        return None
    if not include_nongames and not _library_result_is_game(obj):
        return None
    ent_id = str(
        obj.get("productEntitlementId")
        or obj.get("id")
        or obj.get("machine_name")
        or ""
    ).strip()
    name = str(obj.get("title") or obj.get("human_name") or ent_id or "").strip()
    if not ent_id and not name:
        return None
    machine = ent_id or name
    image = None
    for key in ("image", "icon", "header_image", "library_image", "cover"):
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            image = val
            break
    steam_id = _steam_app_from_library_result(obj)
    methods = obj.get("deliveryMethods") or []
    redeemed = obj.get("redeemed") if isinstance(obj.get("redeemed"), bool) else None
    if redeemed is None and isinstance(methods, list) and "steam" in [str(m).lower() for m in methods]:
        # List UI no longer exposes redeemed clearly; leave unknown.
        redeemed = None
    store_url = _store_url(machine, steam_id)
    if not steam_id and ent_id:
        store_url = f"https://www.humblebundle.com/home/library/{quote(ent_id, safe='')}"
    gamekey = str(obj.get("orderId") or obj.get("gamekey") or ent_id or "")
    return LibraryItem(
        machine_name=machine,
        name=name or machine,
        image_url=image,
        store_url=store_url,
        gamekey=gamekey,
        redeemed=redeemed,
        steam_app_id=steam_id,
    )


def _dom_library_rows(page) -> list[dict]:
    raw = page.evaluate(
        """() => {
          const out = [];
          const seen = new Set();
          for (const a of document.querySelectorAll('a[href*="/home/library/"]')) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/\\/home\\/library\\/(?!content\\/|group\\/)([^/?#]+)/);
            if (!m) continue;
            const id = decodeURIComponent(m[1]);
            if (!id || seen.has(id)) continue;
            seen.add(id);
            const title = (a.getAttribute('title') || a.textContent || '').replace(/\\s+/g, ' ').trim();
            out.push({ id, productEntitlementId: id, title, href });
          }
          return JSON.stringify(out);
        }""",
        timeout=20,
    )
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


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


def fetch_library_items(
    *,
    include_nongames: bool = False,
    dump: bool = False,
) -> list[LibraryItem]:
    """Fetch all library items using the saved Humble profile (redesign UI path)."""
    from auth.cdp_browser import STEALTH_INIT_SCRIPT, close_browser_bounded, launch_persistent_profile

    profile = profile_dir("humble")
    if not profile.exists():
        raise RuntimeError(
            "No saved Humble profile at cache/auth/profiles/humble. "
            "Open the Connections page and connect Humble Bundle first."
        )

    captured_payloads: list[dict[str, Any]] = []
    dump_samples: list[dict[str, Any]] = []

    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_LIB_WINDOW_POS,
        window_size=_LIB_WINDOW_SIZE,
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
                if action != FILTER_USER_LIBRARY_ACTION and "home/library" not in url:
                    return
                if action and action != FILTER_USER_LIBRARY_ACTION:
                    return
                if int(getattr(resp, "status", 0) or 0) != 200:
                    return
                text = resp.text()
                payload = _extract_filter_user_library_payload(text)
                if payload:
                    captured_payloads.append(payload)
                    if dump:
                        dump_samples.append({"url": getattr(resp, "url", ""), "payload": payload})
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

        # Session probe (new auth); fail fast when clearly anonymous.
        try:
            status_resp = ctx.request.get(SESSION_STATUS_URL, timeout=15_000)
            if status_resp.status == 200:
                body = (status_resp.text() or "").strip()
                if body.startswith("{"):
                    from auth.connect_extractors import humble_session_status_authenticated

                    if not humble_session_status_authenticated(json.loads(body)):
                        raise RuntimeError("Humble session expired")
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass

        page.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + _CLEARANCE_WAIT_SEC
        while time.time() < deadline:
            if _page_looks_signed_out(page):
                raise RuntimeError("Humble session expired")
            if captured_payloads or _dom_library_rows(page):
                break
            page.wait_for_timeout(1000)

        if _page_looks_signed_out(page):
            raise RuntimeError("Humble session expired")

        found: dict[str, LibraryItem] = {}
        page_num = 1
        total_pages = 1
        empty_streak = 0

        while page_num <= max(total_pages, page_num) and page_num <= 500:
            if page_num > 1:
                target = f"{LIBRARY_URL}?page={page_num}"
                print(f"[library page {page_num}] {target}", flush=True)
                before = len(captured_payloads)
                page.goto(target, wait_until="domcontentloaded", timeout=60_000)
                wait_deadline = time.time() + 15
                while time.time() < wait_deadline and len(captured_payloads) == before:
                    if _page_looks_signed_out(page):
                        raise RuntimeError("Humble session expired")
                    page.wait_for_timeout(500)

            page_items: list[LibraryItem] = []
            # Prefer the newest matching action payload for this page.
            for payload in reversed(captured_payloads):
                pag = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
                payload_page = int(pag.get("page") or 0) or page_num
                if payload_page not in (0, page_num):
                    continue
                total_pages = max(total_pages, int(pag.get("totalPages") or total_pages) or 1)
                for raw in payload.get("results") or []:
                    item = _item_from_library_result(raw, include_nongames=include_nongames)
                    if item:
                        page_items.append(item)
                if page_items:
                    break

            if not page_items:
                for raw in _dom_library_rows(page):
                    item = _item_from_library_result(raw, include_nongames=include_nongames)
                    if item:
                        page_items.append(item)

            new_count = 0
            for item in page_items:
                if item.machine_name not in found:
                    found[item.machine_name] = item
                    new_count += 1

            print(
                f"  page {page_num}: {len(page_items)} rows ({new_count} new), "
                f"totalPages~{total_pages}",
                flush=True,
            )

            if not page_items:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0

            if page_num >= total_pages and total_pages > 1:
                break
            # If pagination metadata never arrived, stop when a page adds nothing.
            if total_pages == 1 and page_num > 1 and new_count == 0:
                break
            if total_pages == 1 and page_num == 1 and page_items:
                # Try page 2 once to discover whether more pages exist.
                total_pages = 2
            page_num += 1
            time.sleep(_PAGE_DELAY_SEC)

        if dump:
            dump_path().parent.mkdir(parents=True, exist_ok=True)
            dump_path().write_text(
                json.dumps(
                    {
                        "payload_count": len(captured_payloads),
                        "samples": dump_samples[:5] or captured_payloads[:3],
                        "item_count": len(found),
                        "items": [
                            {
                                "machine_name": it.machine_name,
                                "name": it.name,
                                "store_url": it.store_url,
                            }
                            for it in list(found.values())[:20]
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

        if not found:
            # Last resort: legacy orders API if Humble restores it.
            try:
                orders_raw = _api_get(ctx, ORDERS_URL)
            except Exception as exc:  # noqa: BLE001
                if _signed_out(exc):
                    raise RuntimeError("Humble session expired") from exc
                raise RuntimeError(
                    "Humble library page returned no items (redesign UI empty or blocked)"
                ) from exc
            if isinstance(orders_raw, list) and orders_raw:
                for i, entry in enumerate(orders_raw, 1):
                    if not isinstance(entry, dict):
                        continue
                    gamekey = entry.get("gamekey")
                    if not gamekey:
                        continue
                    print(f"[legacy order {i}/{len(orders_raw)}] {gamekey}", flush=True)
                    try:
                        detail = _api_get(ctx, ORDER_DETAIL_URL.format(gamekey=gamekey))
                    except Exception as exc:  # noqa: BLE001
                        print(f"  skip order {gamekey}: {exc}", flush=True)
                        time.sleep(ORDER_DELAY_SEC)
                        continue
                    for item in _parse_order_detail(detail, include_nongames=include_nongames):
                        found[item.machine_name] = item
                    time.sleep(ORDER_DELAY_SEC)

        return sorted(found.values(), key=lambda x: x.name.lower())
    finally:
        close_browser_bounded(ctx)


def _build_row(item: LibraryItem, hltb: dict | None) -> dict:
    tags: list[str] = []
    if item.redeemed is False:
        tags.append("unredeemed key")
    if item.steam_app_id:
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


def _load_existing_by_machine() -> dict[str, dict]:
    if not catalog_file(GAMES_HUMBLE_JSON).exists():
        return {}
    try:
        data = json.loads(catalog_file(GAMES_HUMBLE_JSON).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    for g in data.get("games", []):
        if isinstance(g, dict) and g.get("humble_id"):
            out[str(g["humble_id"])] = g
    return out


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
        if "expired" in msg.lower() or "401" in msg or "403" in msg:
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
    existing = _load_existing_by_machine()
    rows: list[dict] = []
    loop_hb = HeartbeatTimer(interval=25.0)
    for i, item in enumerate(items, 1):
        cached = existing.get(item.machine_name)
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
        existing,
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
