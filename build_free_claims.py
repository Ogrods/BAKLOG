#!/usr/bin/env python3
"""Build the published free-claims feed from maintainer input + Steam enrichment."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from fetchers._progress import RunStats, started
from shared.free_claims_sources import GAMERPOWER_ATTRIBUTION, merge_manual_and_auto, norm_title
from shared.profile_paths import free_claims_path
from shared.safe_write import safe_write_text
from shared.steam_match import appid_from_steam_url, pick_appid, strip_giveaway_decorations

INPUT_PATH = Path("free-claims.input.json")
AUTO_PATH = Path("curated/free_claims.auto.json")
APPROVED_PATH = Path("curated/free_claims.approved.json")
OUTPUT_PATH = Path("landing/free-claims.json")
FALLBACK_PATH = Path("curated/free_claims.fallback.json")
STORE_DELAY_SEC = 1.5
STEAM_STORESEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}
FIELD_OVERRIDE_KEYS = frozenset({"title", "claim_url", "ends_at"})


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _clean_blurb(raw: object) -> str | None:
    """ITAD blurbs embed raw HTML (anchor tags + literal giveaway URLs + an
    "expires on … | go to giveaway" suffix). Strip the markup so the published
    feed never leaks URLs as visible text in the dashboard."""
    if not raw:
        return None
    text = re.sub(r"<[^>]*>", " ", str(raw))
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'")):
        text = text.replace(entity, char)
    text = re.sub(
        r"\s*\|?\s*(unknown expiry|expires on[^|]*)\s*\|?\s*go to giveaway\s*",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _slug_id(store: str, title: str, appid: int | None = None) -> str:
    if appid:
        return f"{store}-{appid}"
    base = re.sub(r"[^a-z0-9]+", "-", (title or "game").lower()).strip("-")
    return f"{store}-{base}"[:80] or f"{store}-claim"


def _throttle(last_call: list[float]) -> None:
    elapsed = time.time() - last_call[0]
    if elapsed < STORE_DELAY_SEC:
        time.sleep(STORE_DELAY_SEC - elapsed)
    last_call[0] = time.time()


def _steam_app_details(appid: int, last_call: list[float]) -> dict | None:
    _throttle(last_call)
    try:
        resp = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english"},
            timeout=30,
        )
        resp.raise_for_status()
        entry = resp.json().get(str(appid), {})
        if not entry.get("success"):
            return None
        return entry.get("data") or None
    except requests.RequestException:
        return None


def _steam_review_percent(appid: int, last_call: list[float]) -> int | None:
    _throttle(last_call)
    try:
        resp = requests.get(
            f"https://store.steampowered.com/appreviews/{appid}",
            params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
            timeout=30,
        )
        resp.raise_for_status()
        summary = resp.json().get("query_summary") or {}
        total = summary.get("total_reviews") or 0
        pos = summary.get("total_positive") or 0
        if total <= 0:
            return None
        return round(100 * pos / total)
    except requests.RequestException:
        return None


def _steam_storesearch(term: str, last_call: list[float]) -> list[dict]:
    """Return storesearch items for a title (empty list on failure)."""
    if not term:
        return []
    _throttle(last_call)
    try:
        resp = requests.get(
            STEAM_STORESEARCH_URL,
            params={"term": term, "l": "english", "cc": "us"},
            headers=STEAM_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        return items if isinstance(items, list) else []
    except requests.RequestException:
        return []


def _cover_lookup_key(title: str) -> str:
    return norm_title(strip_giveaway_decorations(title))


def _steam_portrait_cover(appid: int) -> str:
    """2:3 library capsule — fills claim-row portrait slots without letterboxing."""
    return f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg"


def _prefer_portrait_cover(header: object, appid: int) -> str | None:
    """Upgrade landscape thumbnails to Steam portrait art when an appid is known."""
    portrait = _steam_portrait_cover(appid)
    if not header:
        return portrait
    current = str(header).strip()
    if not current:
        return portrait
    if _cover_quality(portrait) > _cover_quality(current):
        return portrait
    return current


def _cover_quality(url: str) -> int:
    """Rank a candidate cover URL: higher wins. Favor Steam CDN art over
    GamerPower/other thumbnails so the borrow picks the best available cover."""
    u = (url or "").lower()
    if not u:
        return -1
    if "library_600x900" in u or "library_capsule" in u:
        return 4
    if "steamstatic" in u or "steamcdn" in u or "akamai" in u:
        return 3
    if "epicgames" in u:
        return 2
    return 1


def _build_cover_lookup(items: list[dict]) -> dict[str, str]:
    """Map normalized giveaway title → best cover URL from any source that has one."""
    lookup: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        img = str(item.get("header_image") or "").strip()
        if not img:
            continue
        key = _cover_lookup_key(str(item.get("title") or ""))
        if not key:
            continue
        existing = lookup.get(key)
        if existing is None or _cover_quality(img) > _cover_quality(existing):
            lookup[key] = img
    return lookup


def _appid_from_steam_urls(claim_url: str, blurb: object = None) -> int | None:
    """Extract a Steam appid from giveaway URLs embedded in claim_url or blurb."""
    for text in (claim_url, str(blurb or "")):
        appid = appid_from_steam_url(text)
        if appid is not None:
            return appid
    return None


def _resolve_steam_appid_by_title(title: str, last_call: list[float]) -> int | None:
    """Resolve a Steam appid via storesearch on a decoration-stripped title."""
    term = strip_giveaway_decorations(title)
    if not term:
        return None
    items = _steam_storesearch(term, last_call)
    return pick_appid(items, term)


def _resolve_steam_appid(
    *,
    store: str,
    title: str,
    claim_url: str,
    blurb: object = None,
    last_call: list[float],
) -> int | None:
    """Resolve a Steam appid from URL or decoration-stripped title search."""
    appid = _appid_from_steam_urls(claim_url, blurb)
    if appid is not None:
        return appid
    if store != "steam":
        return None
    return _resolve_steam_appid_by_title(title, last_call)


_ITCH_HINT = re.compile(r"itch\.?io", re.IGNORECASE)


def _infer_store_from_text(store: str, title: str, blurb: object, claim_url: str) -> str:
    """GamerPower often tags itch.io giveaways as store='other'. Infer from text."""
    if store and store != "other":
        return store
    haystack = " ".join(
        part for part in (title, str(blurb or ""), claim_url) if part
    )
    if _ITCH_HINT.search(haystack):
        return "itch"
    return store or "other"


def _enrich_item(
    raw: dict,
    last_call: list[float],
    cover_lookup: dict[str, str] | None = None,
) -> dict:
    claim_url = str(raw.get("claim_url") or "").strip()
    title = (raw.get("title") or "").strip()
    store = _infer_store_from_text(
        str(raw.get("store") or "").strip().lower(),
        title,
        raw.get("blurb"),
        claim_url,
    )
    appid = raw.get("steam_appid")
    if appid is not None:
        try:
            appid = int(appid)
        except (TypeError, ValueError):
            appid = None

    header = raw.get("header_image")
    genres = raw.get("genres") or []
    review = raw.get("review_percent")

    if appid is None:
        appid = _resolve_steam_appid(
            store=store,
            title=title,
            claim_url=claim_url,
            blurb=raw.get("blurb"),
            last_call=last_call,
        )

    if not header and cover_lookup:
        borrow_key = _cover_lookup_key(title)
        borrowed = cover_lookup.get(borrow_key)
        if borrowed:
            header = borrowed

    if appid is None and (not header or review is None) and store != "steam":
        appid = _resolve_steam_appid_by_title(title, last_call)

    if appid:
        details = _steam_app_details(appid, last_call)
        if details:
            if store in ("steam", ""):
                store = store or "steam"
                title = title or (details.get("name") or "").strip()
            if not genres and store in ("steam", ""):
                genres = [
                    g.get("description")
                    for g in (details.get("genres") or [])
                    if g.get("description")
                ]
            if review is None:
                review = _steam_review_percent(appid, last_call)
        header = _prefer_portrait_cover(header, appid)

    item_id = (raw.get("id") or "").strip() or _slug_id(store, title, appid)
    out = {
        "id": item_id,
        "store": store,
        "title": title or item_id,
        "claim_url": claim_url,
        "header_image": header,
        "genres": genres[:6] if isinstance(genres, list) else [],
        "blurb": _clean_blurb(raw.get("blurb")),
        "ends_at": _normalize_ends_at(raw.get("ends_at")),
    }
    if appid:
        out["steam_appid"] = appid
    if review is not None:
        out["review_percent"] = review
    source = raw.get("source")
    if source:
        out["source"] = source
    return out


def _load_auto_items(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = doc.get("items") or []
    return items if isinstance(items, list) else []


def _load_approved_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = doc.get("ids") or []
    if not isinstance(ids, list):
        return set()
    return {str(item_id).strip() for item_id in ids if str(item_id).strip()}


def _load_store_overrides(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = doc.get("store_overrides") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        k = str(key).strip()
        v = str(val or "").strip().lower()
        if k and v:
            out[k] = v
    return out


def _load_field_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = doc.get("field_overrides") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, val in raw.items():
        item_id = str(key).strip()
        if not item_id or not isinstance(val, dict):
            continue
        cleaned: dict[str, str] = {}
        for field in FIELD_OVERRIDE_KEYS:
            if field not in val:
                continue
            text = str(val[field] or "").strip()
            if text:
                cleaned[field] = text
        if cleaned:
            out[item_id] = cleaned
    return out


def _apply_field_overrides(items: list[dict], field_overrides: dict[str, dict[str, str]]) -> None:
    for item in items:
        item_id = str(item.get("id") or "").strip()
        overrides = field_overrides.get(item_id)
        if not overrides:
            continue
        for field, value in overrides.items():
            item[field] = value


def _parse_ends_at(ends_at: object) -> datetime | None:
    if ends_at is None:
        return None
    text = str(ends_at).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_ends_at(ends_at: object) -> str | None:
    """Canonicalize an ends_at value to UTC ISO-8601 with a ``Z`` suffix.

    Auto sources, manual ``free-claims.input.json`` entries, and admin
    ``field_overrides`` all funnel through here, so the published feed never
    mixes naive/offset/``Z`` formats. Unparseable but non-empty values are kept
    as-is rather than dropped."""
    parsed = _parse_ends_at(ends_at)
    if parsed is None:
        text = str(ends_at or "").strip()
        return text or None
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_expired(ends_at: object, now: datetime) -> bool:
    parsed = _parse_ends_at(ends_at)
    if parsed is None:
        return False
    return parsed < now


def _enrich_item_light(
    raw: dict,
    cover_lookup: dict[str, str] | None = None,
) -> dict:
    """Fast enrich for admin preview — no Steam/network calls."""
    claim_url = str(raw.get("claim_url") or "").strip()
    title = (raw.get("title") or "").strip()
    store = _infer_store_from_text(
        str(raw.get("store") or "").strip().lower(),
        title,
        raw.get("blurb"),
        claim_url,
    )
    appid = raw.get("steam_appid")
    if appid is not None:
        try:
            appid = int(appid)
        except (TypeError, ValueError):
            appid = None

    header = raw.get("header_image")
    genres = raw.get("genres") or []
    review = raw.get("review_percent")
    if not header and cover_lookup:
        borrowed = cover_lookup.get(_cover_lookup_key(title))
        if borrowed:
            header = borrowed

    if appid:
        header = _prefer_portrait_cover(header, appid)

    item_id = (raw.get("id") or "").strip() or _slug_id(store, title, appid)
    out: dict = {
        "id": item_id,
        "store": store,
        "title": title or item_id,
        "claim_url": claim_url,
        "header_image": header,
        "genres": genres[:6] if isinstance(genres, list) else [],
        "blurb": _clean_blurb(raw.get("blurb")),
        "ends_at": _normalize_ends_at(raw.get("ends_at")),
    }
    if appid:
        out["steam_appid"] = appid
    if review is not None:
        out["review_percent"] = review
    source = raw.get("source")
    if source:
        out["source"] = source
    return out


def preview_publish_items(
    *,
    manual_items: list[dict],
    auto_items_all: list[dict],
    approved_ids: set[str],
    store_overrides: dict[str, str] | None = None,
    field_overrides: dict[str, dict[str, str]] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Dry-run merge + prune for admin preview (no disk writes, no Steam API)."""
    store_overrides = store_overrides or {}
    field_overrides = field_overrides or {}
    now = now or datetime.now(UTC)

    auto_items: list[dict] = []
    for item in auto_items_all:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id not in approved_ids:
            continue
        if _is_expired(item.get("ends_at"), now):
            continue
        auto_items.append(dict(item))

    if store_overrides:
        for item in auto_items:
            override = store_overrides.get(str(item.get("id") or "").strip())
            if override:
                item["store"] = override
    if field_overrides:
        _apply_field_overrides(auto_items, field_overrides)

    raw_items = merge_manual_and_auto(manual_items, auto_items)
    cover_lookup = _build_cover_lookup(auto_items_all)
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if not raw.get("claim_url") or not raw.get("store"):
            continue
        if _is_expired(raw.get("ends_at"), now):
            continue
        items.append(_enrich_item_light(raw, cover_lookup))
    return items


def _prune_expired_from_approved(path: Path, expired_ids: set[str]) -> int:
    if not expired_ids or not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    ids = [str(item_id).strip() for item_id in doc.get("ids") or [] if str(item_id).strip()]
    kept_ids = [item_id for item_id in ids if item_id not in expired_ids]
    if len(kept_ids) == len(ids):
        return 0
    doc["ids"] = kept_ids
    store_overrides = doc.get("store_overrides")
    if isinstance(store_overrides, dict):
        doc["store_overrides"] = {
            k: v for k, v in store_overrides.items() if str(k).strip() not in expired_ids
        }
    field_overrides = doc.get("field_overrides")
    if isinstance(field_overrides, dict):
        doc["field_overrides"] = {
            k: v for k, v in field_overrides.items() if str(k).strip() not in expired_ids
        }
    safe_write_text(path, json.dumps(doc, indent=2, ensure_ascii=False))
    return len(ids) - len(kept_ids)


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip writing the active profile's free_claims.json (publish-only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("build_free_claims.py")

    if not args.input.is_file():
        stats.error(f"missing input file: {args.input}")
        return stats.finish("build_free_claims", t0, exit_code=1)

    try:
        doc = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        stats.error(f"could not read input: {exc}")
        return stats.finish("build_free_claims", t0, exit_code=1)

    manual_items = doc.get("items") or []
    if not isinstance(manual_items, list):
        stats.error("input.items must be a list")
        return stats.finish("build_free_claims", t0, exit_code=1)

    auto_items_all = _load_auto_items(AUTO_PATH)
    approved_ids = _load_approved_ids(APPROVED_PATH)
    store_overrides = _load_store_overrides(APPROVED_PATH)
    field_overrides = _load_field_overrides(APPROVED_PATH)
    now = datetime.now(UTC)
    expired_approved_ids: set[str] = set()
    auto_items: list[dict] = []
    for item in auto_items_all:
        item_id = str(item.get("id") or "").strip()
        if item_id not in approved_ids:
            continue
        if _is_expired(item.get("ends_at"), now):
            expired_approved_ids.add(item_id)
            continue
        auto_items.append(item)
    if store_overrides:
        for item in auto_items:
            override = store_overrides.get(str(item.get("id") or "").strip())
            if override:
                item["store"] = override
    if field_overrides:
        _apply_field_overrides(auto_items, field_overrides)
    if expired_approved_ids:
        stats.warn(f"skipped {len(expired_approved_ids)} expired approved auto item(s)")
        if not args.dry_run:
            pruned = _prune_expired_from_approved(APPROVED_PATH, expired_approved_ids)
            if pruned:
                stats.warn(f"pruned {pruned} expired item(s) from approved list")
    if auto_items_all:
        stats.warn(
            f"auto feed: {len(auto_items)} approved of {len(auto_items_all)} available"
        )
    raw_items = merge_manual_and_auto(manual_items, auto_items)
    if auto_items:
        stats.warn(f"merged {len(auto_items)} auto item(s); {len(raw_items)} total before enrich")

    cover_lookup = _build_cover_lookup(auto_items_all)
    last_call = [0.0]
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            stats.warn("skipped non-object item")
            continue
        if not raw.get("claim_url") or not raw.get("store"):
            stats.warn(f"skipped item missing store/claim_url: {raw!r}")
            continue
        if _is_expired(raw.get("ends_at"), now):
            stats.warn(f"skipped expired item: {raw.get('id')!r}")
            continue
        items.append(_enrich_item(raw, last_call, cover_lookup))

    generated_at = datetime.now(UTC).isoformat()
    has_gamerpower = any(item.get("source") == "gamerpower" for item in items)
    payload = {
        "generated_at": generated_at,
        "items": items,
    }
    if has_gamerpower:
        payload["attribution"] = [GAMERPOWER_ATTRIBUTION]
    profile_payload = {
        "fetched_at": generated_at,
        "source_url": "build_free_claims.py",
        "generated_at": generated_at,
        "items": items,
    }
    if has_gamerpower:
        profile_payload["attribution"] = [GAMERPOWER_ATTRIBUTION]
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    profile_text = json.dumps(profile_payload, indent=2, ensure_ascii=False)

    if args.dry_run:
        targets = [args.output, FALLBACK_PATH]
        if not args.no_profile:
            targets.append(free_claims_path())
        print(
            f"dry-run: would write {len(items)} item(s) to {', '.join(str(t) for t in targets)}",
            flush=True,
        )
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_PATH.write_text(text, encoding="utf-8")
        written = [args.output, FALLBACK_PATH]
        if not args.no_profile:
            profile_out = free_claims_path()
            safe_write_text(profile_out, profile_text)
            written.append(profile_out)
        print(
            f"Wrote {len(items)} item(s) to {', '.join(str(p) for p in written)}.",
            flush=True,
        )

    stats.ok = len(items)
    return stats.finish("build_free_claims", t0, exit_code=0, extra=f"{len(items)} item(s)")


if __name__ == "__main__":
    raise SystemExit(main())
