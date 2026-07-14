#!/usr/bin/env python3
"""Build the published free-claims feed from maintainer input + Steam enrichment."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from fetchers._base import configure_stdout, refuse_empty_result
from fetchers._progress import HeartbeatTimer, RunStats, started
from shared.free_claims_sources import (
    CLAIM_ENRICH_FIELDS,
    EPIC_MOBILE_STORE,
    GAMERPOWER_ATTRIBUTION,
    claim_match_keys,
    has_valid_claim_links,
    is_epic_mobile_store,
    merge_manual_and_auto,
    norm_title,
    normalize_claim_urls,
)
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
FIELD_OVERRIDE_KEYS = frozenset({"title", "claim_url", "claim_urls", "ends_at"})
ITAD_GAME_SLUG_RE = re.compile(
    r"isthereanydeal\.com/game/([^/\"'>]+)/info",
    re.IGNORECASE,
)
DEBUG_CLAIMS = os.environ.get("BAKLOG_DEBUG_CLAIMS") == "1"


def _debug_claims(msg: str) -> None:
    if DEBUG_CLAIMS:
        print(f"  [claims-debug] {msg}", flush=True)


def _clean_blurb(raw: object) -> str | None:
    """ITAD blurbs embed raw HTML (anchor tags + literal giveaway URLs + an
    "expires on … | go to giveaway" suffix). Strip the markup so the published
    feed never leaks URLs as visible text in the dashboard.
    Sync pair: js/claim-card.js sanitizeBlurb."""
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
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
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


_verified_portrait_cache: dict[int, bool] = {}


def _verified_portrait_cover(appid: int, last_call: list[float]) -> str | None:
    """Return portrait library_600x900 URL only when the Steam CDN confirms it exists."""
    cached = _verified_portrait_cache.get(appid)
    if cached is not None:
        return _steam_portrait_cover(appid) if cached else None
    url = _steam_portrait_cover(appid)
    _throttle(last_call)
    exists = False
    try:
        resp = requests.head(url, timeout=15, allow_redirects=True)
        exists = resp.status_code == 200
    except Exception:
        exists = False
    _verified_portrait_cache[appid] = exists
    return url if exists else None


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


def _build_review_lookup(items: list[dict]) -> dict[str, int]:
    """Map normalized giveaway title → review_percent from any sibling that has one.

    A game's Steam review % is the same regardless of which store grants the
    freebie, so a store/ITAD copy with no resolved appid can borrow the review
    its sibling (or a prior published row) already carries — same idea as the
    cover borrow.
    """
    lookup: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        review = item.get("review_percent")
        if review is None:
            continue
        try:
            review_int = int(review)
        except (TypeError, ValueError):
            continue
        key = _cover_lookup_key(str(item.get("title") or ""))
        if key and key not in lookup:
            lookup[key] = review_int
    return lookup


def _appid_from_steam_urls(claim_url: str, blurb: object = None) -> int | None:
    """Extract a Steam appid from giveaway URLs embedded in claim_url or blurb."""
    for text in (claim_url, str(blurb or "")):
        appid = appid_from_steam_url(text)
        if appid is not None:
            return appid
    return None


def _itad_slug_from_blurb(blurb: object) -> str | None:
    """Extract a human title from an ITAD game info link embedded in the blurb."""
    match = ITAD_GAME_SLUG_RE.search(str(blurb or ""))
    if not match:
        return None
    slug = match.group(1).strip().replace("-", " ")
    return slug or None


def _resolve_steam_appid_by_title(
    title: str,
    last_call: list[float],
    *,
    blurb: object = None,
) -> int | None:
    """Resolve a Steam appid via storesearch on a decoration-stripped title."""
    term = strip_giveaway_decorations(title)
    if term:
        items = _steam_storesearch(term, last_call)
        appid = pick_appid(items, term)
        if appid is not None:
            return appid
    slug_term = _itad_slug_from_blurb(blurb)
    if slug_term and slug_term.lower() != (term or "").lower():
        items = _steam_storesearch(slug_term, last_call)
        return pick_appid(items, slug_term)
    return None


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
    return _resolve_steam_appid_by_title(title, last_call, blurb=blurb)


_ITCH_HINT = re.compile(r"itch\.?io", re.IGNORECASE)
_INDIEGALA_HINT = re.compile(r"indiegala", re.IGNORECASE)
_MOBILE_EPIC_HINT = re.compile(r"mobile", re.IGNORECASE)
_EGS_EPIC_HINT = re.compile(r"\b(epic|egs)\b", re.IGNORECASE)


def _infer_store_from_text(store: str, title: str, blurb: object, claim_url: str) -> str:
    """GamerPower often tags itch.io/IndieGala giveaways as store='other'. Infer from text."""
    haystack = " ".join(
        part for part in (title, str(blurb or ""), claim_url) if part
    )
    if _MOBILE_EPIC_HINT.search(haystack) and _EGS_EPIC_HINT.search(haystack):
        return EPIC_MOBILE_STORE
    if store and store != "other":
        return store
    if _ITCH_HINT.search(haystack):
        return "itch"
    if _INDIEGALA_HINT.search(haystack):
        return "indiegala"
    return store or "other"


DEFAULT_EXPIRY_SOURCES = frozenset({"epic", "gamerpower", "itad"})
DEFAULT_EXPIRY_DAYS = 14


def _claim_links_payload(raw: dict, store: str) -> dict[str, object]:
    """Outbound link fields for a published claim row."""
    if is_epic_mobile_store(store):
        urls = normalize_claim_urls(raw.get("claim_urls"))
        return {"claim_urls": urls} if urls else {}
    claim_url = str(raw.get("claim_url") or "").strip()
    return {"claim_url": claim_url} if claim_url else {}


def _clean_field_override_entry(val: dict) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for field in FIELD_OVERRIDE_KEYS:
        if field not in val:
            continue
        if field == "claim_urls":
            urls = normalize_claim_urls(val[field])
            if urls:
                cleaned["claim_urls"] = urls
            continue
        text = str(val[field] or "").strip()
        if text:
            cleaned[field] = text
    return cleaned


def _enrich_item_publish_skip(
    store: str,
    appid: int | None,
    header: object,
    genres: list,
    review: object,
) -> bool:
    """True when a publish rebuild can reuse existing metadata without Steam calls."""
    header_str = str(header or "").strip()
    if not header_str or review is None or appid is None:
        return False
    if store in ("steam", "") and not genres:
        return False
    return True


def _enrich_item(
    raw: dict,
    last_call: list[float],
    cover_lookup: dict[str, str] | None = None,
    *,
    now: datetime | None = None,
    upgrade_covers: bool = True,
    prior_row: dict | None = None,
    is_manual: bool = False,
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

    if cover_lookup:
        borrow_key = _cover_lookup_key(title)
        borrowed = cover_lookup.get(borrow_key)
        if borrowed:
            current = str(header or "").strip()
            if not current or _cover_quality(borrowed) > _cover_quality(current):
                header = borrowed

    if appid is None and (not header or review is None) and store != "steam":
        appid = _resolve_steam_appid_by_title(title, last_call, blurb=raw.get("blurb"))

    needs_details = False
    needs_portrait = False
    publish_skip = False
    if appid:
        header_str = str(header or "").strip()
        publish_skip = not upgrade_covers and _enrich_item_publish_skip(
            store, appid, header_str, genres, review
        )
        if publish_skip:
            needs_details = False
            needs_portrait = False
        else:
            needs_details = (
                review is None
                or not header_str
                or (store in ("steam", "") and not genres)
            )
            needs_portrait = upgrade_covers and _cover_quality(header_str) < 4

        real_header = None
        if needs_details:
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
                raw_header = (details.get("header_image") or "").strip()
                if raw_header:
                    real_header = raw_header

        verified_portrait = None
        if needs_portrait:
            verified_portrait = _verified_portrait_cover(appid, last_call)
        header = verified_portrait or real_header or header

    item_id = (raw.get("id") or "").strip() or _slug_id(store, title, appid)
    out = {
        "id": item_id,
        "store": store,
        "title": title or item_id,
        **_claim_links_payload(raw, store),
        "header_image": header,
        "genres": genres[:6] if isinstance(genres, list) else [],
        "blurb": _clean_blurb(raw.get("blurb")),
        "ends_at": _resolve_ends_at(raw, now=now),
    }
    if appid:
        out["steam_appid"] = appid
    if review is not None:
        out["review_percent"] = review
    source = raw.get("source")
    if source:
        out["source"] = source
    first_seen = _resolve_first_seen(
        raw,
        prior_row=prior_row,
        now=now,
        is_manual=is_manual,
    )
    if first_seen:
        out["first_seen"] = first_seen
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


def _load_prior_published_rows(paths: list[Path]) -> dict[str, dict]:
    """Map id -> last published row from prior feed files (earlier paths win).

    Used to carry an approved claim forward when it momentarily falls out of the
    freshly fetched auto feed (upstream source hiccup) so it isn't silently
    dropped from the published feed before it actually expires or is dismissed.
    """
    by_id: dict[str, dict] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in doc.get("items") or []:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or "").strip()
            if row_id and row_id not in by_id:
                by_id[row_id] = row
    return by_id


def _carry_forward_missing_approved(
    published_items: list[dict],
    *,
    approved_ids: set[str],
    dismissed_ids: set[str],
    prior_rows_by_id: dict[str, dict],
    now: datetime,
) -> list[dict]:
    """Return prior published rows for approved claims missing from this build.

    A claim is carried only when it is still approved, not dismissed, not already
    represented in ``published_items`` (by id or dedup key — covers a game that
    came back under a new source id), and not expired.
    """
    published_ids = {str(it.get("id") or "").strip() for it in published_items}
    published_keys: set[str] = set()
    for it in published_items:
        published_keys |= claim_match_keys(it)

    carried: list[dict] = []
    seen_keys: set[str] = set()
    for item_id in approved_ids:
        if item_id in dismissed_ids or item_id in published_ids:
            continue
        row = prior_rows_by_id.get(item_id)
        if not row:
            continue
        keys = claim_match_keys(row)
        if keys & published_keys or keys & seen_keys:
            continue
        if _is_expired(row.get("ends_at"), now):
            continue
        carried.append(dict(row))
        seen_keys |= keys or {f"id:{item_id}"}
    return carried


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


def _load_id_list(path: Path, key: str) -> set[str]:
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = doc.get(key) or []
    if not isinstance(values, list):
        return set()
    return {str(item_id).strip() for item_id in values if str(item_id).strip()}


def _load_dismissed_ids(path: Path) -> set[str]:
    return _load_id_list(path, "dismissed")


def _load_dismissed_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys = doc.get("dismissed_keys") or []
    return {str(k).strip() for k in keys if isinstance(k, str) and k.strip()}


def _load_blocked_ids(path: Path) -> set[str]:
    """Permanently blocked claim ids — hidden from the feed and the review modal."""
    return _load_id_list(path, "blocked")


def _load_premium_only_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    premium_only = doc.get("premium_only_ids") or []
    if not isinstance(premium_only, list):
        return set()
    return {str(item_id).strip() for item_id in premium_only if str(item_id).strip()}


def _manual_premium_only_ids(manual_items: list[dict]) -> set[str]:
    out: set[str] = set()
    for item in manual_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id and item.get("premium_only") is True:
            out.add(item_id)
    return out


def require_manual_approval_enabled(*, env: bool | None = None, cli_flag: bool = False) -> bool:
    """True when manual rows need an explicit ``approved: true`` to publish."""
    if cli_flag:
        return True
    if env is not None:
        return env
    return os.environ.get("BAKLOG_REQUIRE_MANUAL_APPROVAL") == "1"


def manual_row_publishable(item: dict, *, require_manual_approval: bool) -> bool:
    """Whether a manual input row should reach the published feed."""
    if not isinstance(item, dict):
        return False
    if require_manual_approval:
        return item.get("approved") is True
    return item.get("approved") is not False


def filter_manual_items_for_publish(
    manual_items: list[dict],
    *,
    require_manual_approval: bool,
) -> list[dict]:
    return [
        item
        for item in manual_items
        if isinstance(item, dict) and manual_row_publishable(
            item, require_manual_approval=require_manual_approval
        )
    ]


def _apply_premium_only(
    items: list[dict],
    *,
    premium_only_ids: set[str],
    manual_items: list[dict],
) -> None:
    """Stamp or clear premium_only on published rows from approval + manual flags."""
    manual_premium = _manual_premium_only_ids(manual_items)
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if item_id in premium_only_ids or item_id in manual_premium:
            item["premium_only"] = True
        else:
            item.pop("premium_only", None)


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
        cleaned: dict[str, object] = {}
        for field in FIELD_OVERRIDE_KEYS:
            if field not in val:
                continue
            if field == "claim_urls":
                urls = normalize_claim_urls(val[field])
                if urls:
                    cleaned["claim_urls"] = urls
                continue
            text = str(val[field] or "").strip()
            if text:
                cleaned[field] = text
        if cleaned:
            out[item_id] = cleaned
    return out


def _auto_items_by_id(auto_items_all: list[dict]) -> dict[str, dict]:
    return {
        str(item.get("id") or "").strip(): item
        for item in auto_items_all
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _keys_for_approved_id(
    item_id: str,
    *,
    auto_by_id: dict[str, dict],
    field_overrides: dict[str, dict[str, str]],
) -> set[str]:
    """Resolve stable match keys for an approved id (row in feed or field_overrides title)."""
    row = auto_by_id.get(item_id)
    if row:
        keys = claim_match_keys(row)
        if keys:
            return keys
    fo = field_overrides.get(item_id) or {}
    title = str(fo.get("title") or "").strip()
    if title:
        norm = norm_title(title)
        if norm:
            return {f"title:{norm}"}
    return set()


def _resolve_approved_keys(
    approved_ids: set[str],
    auto_items_all: list[dict],
    field_overrides: dict[str, dict[str, str]],
) -> set[str]:
    auto_by_id = _auto_items_by_id(auto_items_all)
    keys: set[str] = set()
    for item_id in approved_ids:
        keys |= _keys_for_approved_id(
            item_id,
            auto_by_id=auto_by_id,
            field_overrides=field_overrides,
        )
    return keys


def _build_key_override_maps(
    approved_ids: set[str],
    *,
    auto_by_id: dict[str, dict],
    store_overrides: dict[str, str],
    field_overrides: dict[str, dict[str, str]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Re-key store/field overrides so they follow a game across feed id flips."""
    store_by_key: dict[str, str] = {}
    field_by_key: dict[str, dict[str, str]] = {}
    for item_id in approved_ids:
        keys = _keys_for_approved_id(
            item_id,
            auto_by_id=auto_by_id,
            field_overrides=field_overrides,
        )
        store_val = store_overrides.get(item_id)
        field_val = field_overrides.get(item_id)
        for key in keys:
            if store_val and key not in store_by_key:
                store_by_key[key] = store_val
            if field_val and key not in field_by_key:
                field_by_key[key] = field_val
    return store_by_key, field_by_key


def _is_approved_item(
    item: dict,
    *,
    approved_ids: set[str],
    approved_keys: set[str],
) -> bool:
    item_id = str(item.get("id") or "").strip()
    if item_id in approved_ids:
        return True
    if approved_keys and claim_match_keys(item) & approved_keys:
        return True
    return False


def _lookup_store_override(
    item: dict,
    *,
    store_overrides: dict[str, str],
    store_overrides_by_key: dict[str, str],
) -> str | None:
    item_id = str(item.get("id") or "").strip()
    override = store_overrides.get(item_id)
    if override:
        return override
    for key in claim_match_keys(item):
        override = store_overrides_by_key.get(key)
        if override:
            return override
    return None


def _lookup_field_overrides(
    item: dict,
    *,
    field_overrides: dict[str, dict[str, str]],
    field_overrides_by_key: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    item_id = str(item.get("id") or "").strip()
    overrides = field_overrides.get(item_id)
    if overrides:
        return overrides
    for key in claim_match_keys(item):
        overrides = field_overrides_by_key.get(key)
        if overrides:
            return overrides
    return None


def _apply_store_overrides(
    items: list[dict],
    *,
    store_overrides: dict[str, str],
    store_overrides_by_key: dict[str, str] | None = None,
) -> None:
    store_overrides_by_key = store_overrides_by_key or {}
    for item in items:
        override = _lookup_store_override(
            item,
            store_overrides=store_overrides,
            store_overrides_by_key=store_overrides_by_key,
        )
        if override:
            item["store"] = override


def _apply_field_overrides(
    items: list[dict],
    field_overrides: dict[str, dict[str, str]],
    field_overrides_by_key: dict[str, dict[str, str]] | None = None,
) -> None:
    field_overrides_by_key = field_overrides_by_key or {}
    for item in items:
        overrides = _lookup_field_overrides(
            item,
            field_overrides=field_overrides,
            field_overrides_by_key=field_overrides_by_key,
        )
        if not overrides:
            continue
        for field, value in overrides.items():
            item[field] = value


def _effective_ends_at(
    item: dict,
    *,
    field_overrides: dict[str, dict[str, str]] | None = None,
    field_overrides_by_key: dict[str, dict[str, str]] | None = None,
) -> object:
    """ends_at after admin field overrides (used before expiry filtering/prune)."""
    overrides = _lookup_field_overrides(
        item,
        field_overrides=field_overrides or {},
        field_overrides_by_key=field_overrides_by_key or {},
    )
    if overrides and "ends_at" in overrides:
        return overrides["ends_at"]
    return item.get("ends_at")


def _select_approved_auto_items(
    auto_items_all: list[dict],
    *,
    approved_ids: set[str],
    approved_keys: set[str],
    now: datetime,
    dismissed_ids: set[str] | None = None,
    field_overrides: dict[str, dict[str, str]] | None = None,
    field_overrides_by_key: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict], set[str]]:
    """Return live approved auto rows and expired approved ids eligible for pruning."""
    dismissed_ids = dismissed_ids or set()
    expired_approved_ids: set[str] = set()
    auto_items: list[dict] = []
    for item in auto_items_all:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id and item_id in dismissed_ids:
            continue
        if not _is_approved_item(
            item,
            approved_ids=approved_ids,
            approved_keys=approved_keys,
        ):
            continue
        ends_at = _effective_ends_at(
            item,
            field_overrides=field_overrides,
            field_overrides_by_key=field_overrides_by_key,
        )
        if _is_expired(ends_at, now):
            if item_id in approved_ids:
                expired_approved_ids.add(item_id)
            continue
        auto_items.append(dict(item))
    return auto_items, expired_approved_ids


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


def _resolve_ends_at(raw: dict, *, now: datetime | None = None) -> str | None:
    """Normalize ends_at or assign a 2-week default for dated giveaway sources."""
    raw_val = raw.get("ends_at")
    if raw_val is not None and str(raw_val).strip():
        return _normalize_ends_at(raw_val)
    source = (raw.get("source") or "").strip().lower()
    if source not in DEFAULT_EXPIRY_SOURCES:
        return None
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    anchor = _parse_ends_at(raw.get("first_seen")) or clock
    default_end = anchor + timedelta(days=DEFAULT_EXPIRY_DAYS)
    return default_end.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_first_seen(
    raw: dict,
    *,
    prior_row: dict | None,
    now: datetime | None,
    is_manual: bool,
) -> str | None:
    """Resolve first_seen for publish output; stamp manual rows on first publish."""
    existing = _normalize_ends_at(raw.get("first_seen"))
    if existing:
        return existing
    if is_manual and prior_row:
        prior = _normalize_ends_at(prior_row.get("first_seen"))
        if prior:
            return prior
    if not is_manual:
        return None
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return clock.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_expired(ends_at: object, now: datetime) -> bool:
    parsed = _parse_ends_at(ends_at)
    if parsed is None:
        return False
    return parsed < now


def _live_items_by_id(live_items: list[dict] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in live_items or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id:
            out[item_id] = item
    return out


def _enrich_item_light(
    raw: dict,
    cover_lookup: dict[str, str] | None = None,
    live_item: dict | None = None,
    review_lookup: dict[str, int] | None = None,
    *,
    now: datetime | None = None,
    prior_row: dict | None = None,
    is_manual: bool = False,
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
    if live_item is not None:
        live_header = str(live_item.get("header_image") or "").strip()
        if live_header:
            current = str(header or "").strip()
            if not current or _cover_quality(live_header) >= _cover_quality(current):
                header = live_header
        if review is None:
            live_review = live_item.get("review_percent")
            if live_review is not None:
                review = live_review
    # Title-keyed fallback: a re-keyed copy (e.g. ITAD id kept over the Epic
    # sibling) won't id-match the live row, so borrow the review by title.
    if review is None and review_lookup:
        borrowed_review = review_lookup.get(_cover_lookup_key(title))
        if borrowed_review is not None:
            review = borrowed_review
    if cover_lookup:
        borrowed = cover_lookup.get(_cover_lookup_key(title))
        if borrowed:
            current = str(header or "").strip()
            if not current or _cover_quality(borrowed) > _cover_quality(current):
                header = borrowed

    if appid and not header:
        header = _steam_portrait_cover(appid)

    item_id = (raw.get("id") or "").strip() or _slug_id(store, title, appid)
    out: dict = {
        "id": item_id,
        "store": store,
        "title": title or item_id,
        **_claim_links_payload(raw, store),
        "header_image": header,
        "genres": genres[:6] if isinstance(genres, list) else [],
        "blurb": _clean_blurb(raw.get("blurb")),
        "ends_at": _resolve_ends_at(raw, now=now),
    }
    if appid:
        out["steam_appid"] = appid
    if review is not None:
        out["review_percent"] = review
    source = raw.get("source")
    if source:
        out["source"] = source
    first_seen = _resolve_first_seen(
        raw,
        prior_row=prior_row or live_item,
        now=now,
        is_manual=is_manual,
    )
    if first_seen:
        out["first_seen"] = first_seen
    return out


from shared.free_claims_sources import norm_title as _norm_title_key  # noqa: E402, I001 — module-level, deliberately placed before preview fn

# Stopwords matching js/claims-workspace.js DUPE_STOPWORDS — removed from
# dismissed_keys filters so the Python side matches JS coverLookupKey() output.
_COVER_STOPWORDS: set[str] = {"a", "an", "and", "the", "of"}

def _cover_lookup_key(title: str) -> str:
    """Looser key matching JS ``coverLookupKey`` — drops connector stopwords.
    Sync pair: admin/claims-workspace.js ``coverLookupKey``
    """
    base = _norm_title_key(title)
    parts = [w for w in base.split() if w and w not in _COVER_STOPWORDS]
    return " ".join(parts).strip()

def preview_publish_items(
    *,
    manual_items: list[dict],
    auto_items_all: list[dict],
    approved_ids: set[str],
    store_overrides: dict[str, str] | None = None,
    field_overrides: dict[str, dict[str, str]] | None = None,
    dismissed_ids: set[str] | None = None,
    dismissed_keys: set[str] | None = None,
    live_items: list[dict] | None = None,
    premium_only_ids: set[str] | None = None,
    require_manual_approval: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    """Dry-run merge + prune for admin preview (no disk writes, no Steam API)."""
    store_overrides = store_overrides or {}
    field_overrides = field_overrides or {}
    dismissed_keys = dismissed_keys or set()
    now = now or datetime.now(UTC)
    live_by_id = _live_items_by_id(live_items)

    auto_by_id = _auto_items_by_id(auto_items_all)
    approved_keys = _resolve_approved_keys(approved_ids, auto_items_all, field_overrides)
    store_by_key, field_by_key = _build_key_override_maps(
        approved_ids,
        auto_by_id=auto_by_id,
        store_overrides=store_overrides,
        field_overrides=field_overrides,
    )
    auto_items, _ = _select_approved_auto_items(
        auto_items_all,
        approved_ids=approved_ids,
        approved_keys=approved_keys,
        now=now,
        dismissed_ids=dismissed_ids,
        field_overrides=field_overrides,
        field_overrides_by_key=field_by_key,
    )
    # Filter by dismissed title keys (stable across feed refreshes).
    # Uses _cover_lookup_key to match JS coverLookupKey() so stopwords
    # ("a", "an", "and", "the", "of") are stripped the same way.
    if dismissed_keys:
        auto_items = [
            it for it in auto_items
            if _cover_lookup_key(it.get("title") or "") not in dismissed_keys
        ]

    if store_overrides or store_by_key:
        _apply_store_overrides(
            auto_items,
            store_overrides=store_overrides,
            store_overrides_by_key=store_by_key,
        )
    if field_overrides or field_by_key:
        _apply_field_overrides(
            auto_items,
            field_overrides,
            field_overrides_by_key=field_by_key,
        )

    publish_manual = filter_manual_items_for_publish(
        manual_items,
        require_manual_approval=require_manual_approval,
    )
    manual_ids = {
        str(it.get("id") or "").strip()
        for it in publish_manual
        if str(it.get("id") or "").strip()
    }
    raw_items = merge_manual_and_auto(publish_manual, auto_items)
    cover_lookup = _build_cover_lookup(auto_items_all)
    review_lookup = _build_review_lookup(list(live_by_id.values()) + auto_items_all)
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if not has_valid_claim_links(raw) or not raw.get("store"):
            continue
        if _is_expired(_resolve_ends_at(raw, now=now), now):
            continue
        item_id = str(raw.get("id") or "").strip()
        items.append(
            _enrich_item_light(
                raw,
                cover_lookup,
                live_by_id.get(item_id),
                review_lookup=review_lookup,
                now=now,
                prior_row=live_by_id.get(item_id),
                is_manual=item_id in manual_ids,
            )
        )
    # Mirror the build's carry-forward: an approved claim that momentarily falls
    # out of the fresh auto feed is kept in the published feed from the prior
    # build, so the preview must do the same or it falsely reports "removed".
    carried = _carry_forward_missing_approved(
        items,
        approved_ids=approved_ids,
        dismissed_ids=dismissed_ids or set(),
        prior_rows_by_id=live_by_id,
        now=now,
    )
    items.extend(carried)
    _apply_premium_only(
        items,
        premium_only_ids=premium_only_ids or set(),
        manual_items=manual_items,
    )
    return items


def _apply_enrich_fields_to_item(target: dict, source: dict) -> bool:
    """Merge enrichment fields from source onto target; returns True when target changed."""
    changed = False
    for field in CLAIM_ENRICH_FIELDS:
        if field == "genres":
            src_genres = source.get("genres")
            if isinstance(src_genres, list) and src_genres and target.get("genres") != src_genres:
                target["genres"] = src_genres
                changed = True
            continue
        src_val = source.get(field)
        if src_val is None or src_val == "":
            continue
        if field == "header_image":
            new_val = str(src_val).strip()
            if new_val and target.get("header_image") != new_val:
                target["header_image"] = new_val
                changed = True
            continue
        if target.get(field) != src_val:
            target[field] = src_val
            changed = True
    return changed


def merge_enriched_items_into_auto_feed(
    auto_path: Path,
    enriched_items: list[dict],
) -> int:
    """Persist enrichment onto the on-disk auto feed matched by item id."""
    if not auto_path.is_file():
        return 0
    try:
        doc = json.loads(auto_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    items = doc.get("items") or []
    if not isinstance(items, list):
        return 0

    by_id = {
        str(item.get("id") or "").strip(): item
        for item in enriched_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not by_id:
        return 0

    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        enriched = by_id.get(item_id)
        if not enriched:
            continue
        if _apply_enrich_fields_to_item(item, enriched):
            updated += 1

    if updated:
        doc["items"] = items
        safe_write_text(auto_path, json.dumps(doc, indent=2, ensure_ascii=False))
    return updated


def merge_enriched_items_into_input_feed(
    input_path: Path,
    enriched_items: list[dict],
) -> int:
    """Persist enrichment onto manual rows in free-claims.input.json matched by id."""
    if not input_path.is_file():
        return 0
    try:
        doc = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    items = doc.get("items") or []
    if not isinstance(items, list):
        return 0

    by_id = {
        str(item.get("id") or "").strip(): item
        for item in enriched_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not by_id:
        return 0

    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        enriched = by_id.get(item_id)
        if not enriched:
            continue
        if _apply_enrich_fields_to_item(item, enriched):
            updated += 1
        src_fs = enriched.get("first_seen")
        if src_fs and item.get("first_seen") != src_fs:
            item["first_seen"] = src_fs
            updated += 1

    if updated:
        doc["items"] = items
        safe_write_text(input_path, json.dumps(doc, indent=2, ensure_ascii=False))
    return updated


def rekey_approved_state(
    *,
    ids: list[str],
    store_overrides: dict[str, str],
    field_overrides: dict[str, dict[str, str]],
    premium_only_ids: set[str],
    auto_items_all: list[dict],
    prior_rows_by_id: dict[str, dict] | None = None,
) -> tuple[list[str], dict[str, str], dict[str, dict[str, str]], set[str]]:
    """Migrate approved ids/overrides when a game re-keys across feed id churn."""
    prior_rows_by_id = prior_rows_by_id or {}
    auto_by_id = _auto_items_by_id(auto_items_all)
    key_to_auto_id: dict[str, str] = {}
    for row in auto_items_all:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        for key in claim_match_keys(row):
            key_to_auto_id.setdefault(key, row_id)

    new_ids: list[str] = []
    seen_ids: set[str] = set()
    new_store: dict[str, str] = {}
    new_field: dict[str, dict[str, str]] = {}
    new_premium: set[str] = set()

    def migrate_maps(old_id: str, new_id: str) -> None:
        if old_id in store_overrides and new_id not in new_store:
            new_store[new_id] = store_overrides[old_id]
        if old_id in field_overrides and new_id not in new_field:
            new_field[new_id] = dict(field_overrides[old_id])
        if old_id in premium_only_ids:
            new_premium.add(new_id)

    for item_id in ids:
        old_id = str(item_id).strip()
        if not old_id:
            continue
        new_id = old_id
        if old_id not in auto_by_id:
            keys = _keys_for_approved_id(
                old_id,
                auto_by_id=auto_by_id,
                field_overrides=field_overrides,
            )
            if not keys and old_id in prior_rows_by_id:
                keys = claim_match_keys(prior_rows_by_id[old_id])
            resolved = None
            for key in keys:
                resolved = key_to_auto_id.get(key)
                if resolved:
                    break
            if resolved:
                new_id = resolved
            elif auto_items_all and old_id not in prior_rows_by_id:
                continue
        if new_id in seen_ids:
            migrate_maps(old_id, new_id)
            continue
        seen_ids.add(new_id)
        new_ids.append(new_id)
        migrate_maps(old_id, new_id)

    return new_ids, new_store, new_field, new_premium


def parse_approved_put_payload(payload: dict) -> dict:
    """Normalize admin approved PUT body into prepare_approved_document kwargs."""
    ids = [str(item_id).strip() for item_id in payload.get("ids") or [] if str(item_id).strip()]
    id_set = set(ids)
    store_overrides: dict[str, str] = {}
    for key, val in (payload.get("store_overrides") or {}).items():
        k = str(key).strip()
        v = str(val or "").strip().lower()
        if k and v:
            store_overrides[k] = v
    field_overrides: dict[str, dict[str, object]] = {}
    for key, val in (payload.get("field_overrides") or {}).items():
        k = str(key).strip()
        if not k or not isinstance(val, dict):
            continue
        cleaned = _clean_field_override_entry(val)
        if cleaned:
            field_overrides[k] = cleaned
    # Blocked wins over dismissed: a permanently blocked id never lingers in the
    # reviewable dismissed list. Neither list may shadow an approved id.
    blocked: list[str] = []
    seen_blocked: set[str] = set()
    for item_id in payload.get("blocked") or []:
        b = str(item_id).strip()
        if b and b not in id_set and b not in seen_blocked:
            blocked.append(b)
            seen_blocked.add(b)
    dismissed: list[str] = []
    seen_dismissed: set[str] = set()
    for item_id in payload.get("dismissed") or []:
        d = str(item_id).strip()
        if d and d not in id_set and d not in seen_blocked and d not in seen_dismissed:
            dismissed.append(d)
            seen_dismissed.add(d)
    premium_only_ids: set[str] = set()
    for item_id in payload.get("premium_only_ids") or []:
        p = str(item_id).strip()
        if p:
            premium_only_ids.add(p)
    dismissed_keys = [
        str(k).strip() for k in (payload.get("dismissed_keys") or [])
        if str(k).strip()
    ]
    return {
        "ids": ids,
        "store_overrides": store_overrides,
        "field_overrides": field_overrides,
        "premium_only_ids": premium_only_ids,
        "dismissed": dismissed,
        "dismissed_keys": dismissed_keys,
        "blocked": blocked,
    }


def prepare_approved_document(
    *,
    ids: list[str],
    store_overrides: dict[str, str],
    field_overrides: dict[str, dict[str, str]],
    premium_only_ids: set[str],
    dismissed: list[str],
    dismissed_keys: list[str] | None = None,
    auto_items: list[dict],
    blocked: list[str] | None = None,
    prior_rows_by_id: dict[str, dict] | None = None,
) -> dict:
    """Re-key approved state and shape the on-disk approved.json document.

    Soft-hidden (``dismissed``) ids that no longer exist in the source feed are
    orphan-pruned here so the reviewable hidden list self-cycles; ``blocked`` ids
    (a permanent kill list) are kept verbatim so a re-listed claim never returns.
    """
    rekeyed_ids, store, fields, premium = rekey_approved_state(
        ids=ids,
        store_overrides=store_overrides,
        field_overrides=field_overrides,
        premium_only_ids=premium_only_ids,
        auto_items_all=auto_items,
        prior_rows_by_id=prior_rows_by_id,
    )
    id_set = set(rekeyed_ids)
    store = {k: v for k, v in store.items() if k in id_set}
    premium_list = sorted(p for p in premium if p in id_set)
    merged_fields = dict(field_overrides)
    merged_fields.update(fields)
    blocked_list = list(blocked or [])
    blocked_set = set(blocked_list)
    auto_ids = {
        str(it.get("id") or "").strip()
        for it in (auto_items or [])
        if isinstance(it, dict) and str(it.get("id") or "").strip()
    }
    # Orphan-prune dismissed ids: keep only those still in the feed (so the
    # hidden modal stays meaningful). Drop any that became blocked.
    pruned_dismissed = [
        d for d in dismissed
        if d not in blocked_set and (not auto_ids or d in auto_ids)
    ]
    out: dict = {"ids": rekeyed_ids}
    if store:
        out["store_overrides"] = store
    if merged_fields:
        out["field_overrides"] = merged_fields
    if pruned_dismissed:
        out["dismissed"] = pruned_dismissed
    # Preserve dismissed_keys — title-based dismissal survives feed refresh ID churn
    dismissed_keys_list = [k for k in (dismissed_keys or []) if k]
    if dismissed_keys_list:
        out["dismissed_keys"] = dismissed_keys_list
    if blocked_list:
        out["blocked"] = blocked_list
    if premium_list:
        out["premium_only_ids"] = premium_list
    return out


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
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip writing the active profile's free_claims.json (publish-only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow overwriting the published feed with zero items",
    )
    parser.add_argument(
        "--require-manual-approval",
        action="store_true",
        help="Only publish manual rows with approved: true (default: publish unless approved: false)",
    )
    args = parser.parse_args()
    require_manual_approval = require_manual_approval_enabled(cli_flag=args.require_manual_approval)

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
    if DEBUG_CLAIMS:
        by_source: dict[str, int] = {}
        for row in auto_items_all:
            src = str(row.get("source") or "unknown")
            by_source[src] = by_source.get(src, 0) + 1
        _debug_claims(f"auto feed: {len(auto_items_all)} item(s) by source {by_source}")
    approved_ids = _load_approved_ids(APPROVED_PATH)
    # Blocked ids are a permanent kill list; fold them into the dismissed filter
    # so they are excluded from the feed exactly like a soft-hidden claim.
    dismissed_ids = _load_dismissed_ids(APPROVED_PATH) | _load_blocked_ids(APPROVED_PATH)
    dismissed_keys = _load_dismissed_keys(APPROVED_PATH)
    premium_only_ids = _load_premium_only_ids(APPROVED_PATH)
    store_overrides = _load_store_overrides(APPROVED_PATH)
    field_overrides = _load_field_overrides(APPROVED_PATH)
    orig_store_overrides = dict(store_overrides)
    orig_field_overrides = {k: dict(v) for k, v in field_overrides.items()}
    orig_premium_only_ids = set(premium_only_ids)
    orig_approved_ids = set(approved_ids)
    # Snapshot the previously published rows BEFORE we overwrite the output, so an
    # approved claim that briefly drops out of the source feed can be carried
    # forward instead of silently vanishing.
    prior_published_rows = _load_prior_published_rows(
        [args.output, FALLBACK_PATH, free_claims_path()]
    )
    rekeyed_ids, store_overrides, field_overrides, premium_only_ids = rekey_approved_state(
        ids=sorted(approved_ids),
        store_overrides=store_overrides,
        field_overrides=field_overrides,
        premium_only_ids=premium_only_ids,
        auto_items_all=auto_items_all,
        prior_rows_by_id=prior_published_rows,
    )
    approved_ids = set(rekeyed_ids)
    approved_changed = (
        approved_ids != orig_approved_ids
        or store_overrides != orig_store_overrides
        or field_overrides != orig_field_overrides
        or premium_only_ids != orig_premium_only_ids
    )
    if not args.dry_run and approved_changed and APPROVED_PATH.is_file():
        try:
            appr_doc = json.loads(APPROVED_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            appr_doc = {}
        appr_doc["ids"] = rekeyed_ids
        if store_overrides:
            appr_doc["store_overrides"] = store_overrides
        else:
            appr_doc.pop("store_overrides", None)
        if field_overrides:
            appr_doc["field_overrides"] = field_overrides
        else:
            appr_doc.pop("field_overrides", None)
        if premium_only_ids:
            appr_doc["premium_only_ids"] = sorted(premium_only_ids)
        else:
            appr_doc.pop("premium_only_ids", None)
        safe_write_text(APPROVED_PATH, json.dumps(appr_doc, indent=2, ensure_ascii=False))
    now = datetime.now(UTC)
    auto_by_id = _auto_items_by_id(auto_items_all)
    approved_keys = _resolve_approved_keys(approved_ids, auto_items_all, field_overrides)
    store_by_key, field_by_key = _build_key_override_maps(
        approved_ids,
        auto_by_id=auto_by_id,
        store_overrides=store_overrides,
        field_overrides=field_overrides,
    )
    auto_items, expired_approved_ids = _select_approved_auto_items(
        auto_items_all,
        approved_ids=approved_ids,
        approved_keys=approved_keys,
        now=now,
        dismissed_ids=dismissed_ids,
        field_overrides=field_overrides,
        field_overrides_by_key=field_by_key,
    )
    # Filter by dismissed title keys (stable across feed refreshes)
    if dismissed_keys:
        auto_items = [
            it for it in auto_items
            if _cover_lookup_key(it.get("title") or "") not in dismissed_keys
        ]
    if store_overrides or store_by_key:
        _apply_store_overrides(
            auto_items,
            store_overrides=store_overrides,
            store_overrides_by_key=store_by_key,
        )
    if field_overrides or field_by_key:
        _apply_field_overrides(
            auto_items,
            field_overrides,
            field_overrides_by_key=field_by_key,
        )
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
    if DEBUG_CLAIMS:
        _debug_claims(
            f"approved selection: {len(auto_items)} of {len(auto_items_all)} auto; "
            f"dismissed={len(dismissed_ids)} expired_approved={len(expired_approved_ids)}"
        )
    publish_manual = filter_manual_items_for_publish(
        manual_items,
        require_manual_approval=require_manual_approval,
    )
    skipped_manual = max(0, len(manual_items) - len(publish_manual))
    if skipped_manual:
        stats.warn(
            f"skipped {skipped_manual} unapproved manual item(s) "
            f"(require_manual_approval={require_manual_approval})"
        )
    if publish_manual:
        shipped_manual_ids = [
            str(item.get("id") or "").strip()
            for item in publish_manual
            if str(item.get("id") or "").strip()
        ]
        if shipped_manual_ids:
            stats.warn(
                f"manual rows publishing ({len(shipped_manual_ids)}): "
                + ", ".join(shipped_manual_ids)
            )
    raw_items = merge_manual_and_auto(publish_manual, auto_items)
    if auto_items:
        stats.warn(f"merged {len(auto_items)} auto item(s); {len(raw_items)} total before enrich")

    manual_ids = {
        str(it.get("id") or "").strip()
        for it in publish_manual
        if str(it.get("id") or "").strip()
    }
    cover_lookup = _build_cover_lookup(auto_items_all)
    last_call = [0.0]
    items: list[dict] = []
    enrich_total = sum(
        1
        for raw in raw_items
        if isinstance(raw, dict)
        and has_valid_claim_links(raw)
        and raw.get("store")
        and not _is_expired(_resolve_ends_at(raw, now=now), now)
    )
    enrich_hb = HeartbeatTimer(interval=45.0)
    enrich_idx = 0
    for raw in raw_items:
        if not isinstance(raw, dict):
            stats.warn("skipped non-object item")
            continue
        if not has_valid_claim_links(raw) or not raw.get("store"):
            stats.warn(f"skipped item missing store or claim link(s): {raw!r}")
            continue
        if _is_expired(_resolve_ends_at(raw, now=now), now):
            stats.warn(f"skipped expired item: {raw.get('id')!r}")
            continue
        enrich_idx += 1
        item_id = str(raw.get("id") or "").strip() or f"item-{enrich_idx}"
        enrich_hb.tick_progress(enrich_idx, enrich_total, "enrich", item_id)
        items.append(
            _enrich_item(
                raw,
                last_call,
                cover_lookup,
                now=now,
                upgrade_covers=False,
                prior_row=prior_published_rows.get(item_id),
                is_manual=item_id in manual_ids,
            )
        )

    carried = _carry_forward_missing_approved(
        items,
        approved_ids=approved_ids,
        dismissed_ids=dismissed_ids,
        prior_rows_by_id=prior_published_rows,
        now=now,
    )
    if carried:
        stats.warn(
            f"carried forward {len(carried)} approved claim(s) missing from the "
            f"source feed: {', '.join(str(c.get('id')) for c in carried)}"
        )
        if DEBUG_CLAIMS:
            _debug_claims(
                f"carry-forward ids: {', '.join(str(c.get('id')) for c in carried)}"
            )
        items.extend(carried)

    _apply_premium_only(
        items,
        premium_only_ids=premium_only_ids,
        manual_items=manual_items,
    )

    if not args.dry_run:
        auto_ids = {str(it.get("id") or "").strip() for it in auto_items}
        manual_ids = {str(it.get("id") or "").strip() for it in publish_manual}
        to_persist_auto = [
            it for it in items
            if str(it.get("id") or "").strip() in auto_ids
        ]
        to_persist_manual = [
            it for it in items
            if str(it.get("id") or "").strip() in manual_ids
        ]
        persisted_auto = merge_enriched_items_into_auto_feed(AUTO_PATH, to_persist_auto)
        if persisted_auto:
            stats.warn(f"persisted enrichment onto {persisted_auto} auto feed row(s)")
        persisted_manual = merge_enriched_items_into_input_feed(args.input, to_persist_manual)
        if persisted_manual:
            stats.warn(f"persisted enrichment onto {persisted_manual} manual input row(s)")

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
    if DEBUG_CLAIMS:
        pub_by_source: dict[str, int] = {}
        for row in items:
            src = str(row.get("source") or "unknown")
            pub_by_source[src] = pub_by_source.get(src, 0) + 1
        title_keys: dict[str, list[str]] = {}
        for row in items:
            title = norm_title(row.get("title"))
            if not title:
                continue
            title_keys.setdefault(title, []).append(str(row.get("id") or ""))
        dup_titles = sum(1 for ids in title_keys.values() if len(ids) > 1)
        _debug_claims(
            f"publish: {len(items)} item(s) by source {pub_by_source}; "
            f"title collisions={dup_titles}"
        )
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
        empty_code = refuse_empty_result(
            items,
            label="build_free_claims publish set",
            allow_empty=args.allow_empty,
            output_path=args.output,
        )
        if empty_code:
            stats.error("refusing empty publish — re-run with --allow-empty if intentional")
            return stats.finish("build_free_claims", t0, exit_code=empty_code)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(args.output, text)
        FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(FALLBACK_PATH, text)
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
