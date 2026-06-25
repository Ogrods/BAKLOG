"""Merge Nintendo Virtual Game Cards (primary) with eShop transactions (secondary)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import quote

_TRADEMARK_RE = re.compile(r"[™®©]")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)

_EDITION_SUFFIXES = (
    " digital deluxe edition",
    " deluxe edition",
    " gold edition",
    " ultimate edition",
    " complete edition",
    " definitive edition",
    " special edition",
    " collectors edition",
    " collector's edition",
)

_NON_GAME_TITLE_PATTERNS = re.compile(
    r"\b(expansion pass|season pass|fighter pass|\bdlc\b|add-?on content|"
    r"bonus content|upgrade pack|costume pack|skin pack|\bskin\b|coins?\b|"
    r"coin set|soundtrack|artbook|art book|character pack|challenge pack|"
    r"\bpicaro\b|mini digital sound|digital art book|"
    r"nintendo switch online|membership|e?shop\s+card|add-on content bundle)\b",
    re.I,
)

_STREAMING_APP_PATTERNS = re.compile(
    r"\b(hulu|youtube|twitch|crunchyroll|inkypen|pokémon home|pokemon home|"
    r"pokémon tv|pokemon tv)\b",
    re.I,
)

_DELUXE_MARKERS = (
    "digital deluxe",
    "deluxe edition",
    "gold edition",
    "ultimate edition",
)


def clean_nintendo_title(name: str) -> str:
    text = _TRADEMARK_RE.sub("", name or "")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def norm_nintendo_title(name: str) -> str:
    return clean_nintendo_title(name).lower()


def match_nintendo_title_key(name: str) -> str:
    """Aggressive normalize for receipt↔VGC title join (edition suffixes stripped)."""
    key = norm_nintendo_title(name)
    for suffix in _EDITION_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key


def nintendo_store_url(application_id: str | None, name: str) -> str:
    """Best-effort Nintendo store link; application_id (NS UID) is stable when present."""
    app = str(application_id or "").strip()
    if len(app) >= 8:
        return f"https://www.nintendo.com/us/store/products/game/{app}/"
    safe_name = quote((name or "").strip())
    return f"https://www.nintendo.com/us/store/products/{safe_name}/"


def index_existing_rows(existing: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Build title, application_id, and nintendo_id indexes from a catalog cache."""
    by_title: dict[str, dict] = {}
    by_app_id: dict[str, dict] = {}
    by_nintendo_id: dict[str, dict] = {}
    for row in existing.values():
        title_key = norm_nintendo_title(str(row.get("name") or ""))
        if title_key and title_key not in by_title:
            by_title[title_key] = row
        app_id = str(row.get("application_id") or "").strip()
        if app_id and app_id not in by_app_id:
            by_app_id[app_id] = row
        nid = str(row.get("nintendo_id") or row.get("id") or "").strip()
        if nid and nid not in by_nintendo_id:
            by_nintendo_id[nid] = row
    return by_title, by_app_id, by_nintendo_id


def find_existing_row(
    item: dict[str, Any],
    *,
    existing: dict[str, dict],
    by_title: dict[str, dict],
    by_app_id: dict[str, dict],
    by_nintendo_id: dict[str, dict],
) -> dict | None:
    """Resolve a cached row when catalog ids migrate from transaction id to application_id."""
    row_id = str(item.get("id") or "")
    if row_id and row_id in existing:
        return existing[row_id]
    app_id = str(item.get("application_id") or "").strip()
    if app_id and app_id in by_app_id:
        return by_app_id[app_id]
    nid = str(item.get("nintendo_id") or "").strip()
    if nid and nid in by_nintendo_id:
        return by_nintendo_id[nid]
    title_key = norm_nintendo_title(str(item.get("name") or ""))
    if title_key:
        cached = by_title.get(title_key)
        if cached:
            return cached
        return by_title.get(match_nintendo_title_key(str(item.get("name") or "")))
    return None


def index_transactions_by_title(tx_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    for tx in tx_rows:
        name = str(tx.get("name") or "")
        for key in {norm_nintendo_title(name), match_nintendo_title_key(name)}:
            if key and key not in by_title:
                by_title[key] = tx
    return by_title


def lookup_transaction_for_vgc(
    vgc_name: str,
    tx_by_title: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key_fn in (norm_nintendo_title, match_nintendo_title_key):
        tx = tx_by_title.get(key_fn(vgc_name))
        if tx:
            return tx
    return None


def _merge_tags(*tag_lists: list[str] | None) -> list[str]:
    out: list[str] = []
    for tags in tag_lists:
        if not tags:
            continue
        for tag in tags:
            if tag and tag not in out:
                out.append(tag)
    return out


def _hybrid_from_vgc(vgc: dict[str, Any], tx: dict[str, Any] | None) -> dict[str, Any]:
    """Build a hybrid row with VGC as the source of truth; overlay receipt metadata when matched."""
    app_id = str(vgc.get("application_id") or vgc.get("vgc_id") or "").strip()
    item = dict(vgc)
    item["id"] = app_id
    item["nintendo_platform"] = vgc.get("platform")
    tags = _merge_tags(["dlc"] if vgc.get("is_dlc") else [], ["lending"] if vgc.get("is_lending") else [])
    if tx:
        item["nintendo_id"] = str(tx.get("nintendo_id") or tx.get("id") or "") or None
        item["purchase_date"] = tx.get("purchase_date")
        item["device_type"] = tx.get("device_type")
        item["content_type"] = tx.get("content_type")
        item["transaction_name"] = tx.get("name")
        tags = _merge_tags(tags, tx.get("tags"))
        item["ownership_source"] = "both"
    else:
        item["nintendo_id"] = None
        item["purchase_date"] = None
        item["device_type"] = None
        item["content_type"] = None
        item["transaction_name"] = None
        item["ownership_source"] = "vgc"
    item["tags"] = tags
    return item


def _hybrid_from_tx_only(tx: dict[str, Any]) -> dict[str, Any]:
    """Receipt-only row when no VGC entitlement matched (secondary / ~2yr window orphans)."""
    tx_id = str(tx.get("id") or tx.get("nintendo_id") or "")
    return {
        "name": tx["name"],
        "id": tx_id,
        "application_id": None,
        "nintendo_id": tx_id or None,
        "vgc_id": None,
        "purchase_date": tx.get("purchase_date"),
        "device_type": tx.get("device_type"),
        "content_type": tx.get("content_type"),
        "tags": list(tx.get("tags") or []),
        "nintendo_platform": tx.get("device_type"),
        "ownership_source": "transaction",
        "transaction_name": tx.get("name"),
    }


def is_nintendo_playable_game(item: dict[str, Any]) -> bool:
    """True for base-game library rows; false for DLC, skins, streaming apps, etc."""
    if item.get("is_dlc") or item.get("nintendo_is_dlc"):
        return False
    tags = item.get("tags") or []
    if "dlc" in tags:
        has_app = bool(
            item.get("has_application")
            or item.get("has_nx_application")
            or item.get("has_ounce_application")
            or item.get("application_id")
            or item.get("nintendo_has_application")
            or item.get("nintendo_has_nx_application")
            or item.get("nintendo_has_ounce_application")
        )
        if not has_app:
            return False
    name = str(item.get("name") or "")
    if not name.strip():
        return False
    if _NON_GAME_TITLE_PATTERNS.search(name):
        return False
    if _STREAMING_APP_PATTERNS.search(name):
        return False
    return True


def dedupe_deluxe_edition_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When base + deluxe SKUs share a title key, keep the non-deluxe row."""
    by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_base[match_nintendo_title_key(str(row.get("name") or ""))].append(row)

    out: list[dict[str, Any]] = []
    for group in by_base.values():
        if len(group) == 1:
            out.append(group[0])
            continue

        def _rank(row: dict[str, Any]) -> tuple:
            name_l = norm_nintendo_title(str(row.get("name") or ""))
            deluxe = any(marker in name_l for marker in _DELUXE_MARKERS)
            return (
                deluxe,
                row.get("ownership_source") != "both",
                not row.get("application_id"),
            )

        group.sort(key=_rank)
        out.append(group[0])
    return out


def finalize_nintendo_library_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop non-game entitlements and collapse duplicate edition SKUs."""
    kept = [row for row in rows if is_nintendo_playable_game(row)]
    return dedupe_deluxe_edition_rows(kept)


def merge_vgc_with_transactions(
    vgc_rows: list[dict[str, Any]],
    tx_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union entitlements: every VGC card is a row; unmatched receipts are appended."""
    tx_by_title = index_transactions_by_title(tx_rows)
    matched_tx_keys: set[str] = set()
    merged: list[dict[str, Any]] = []

    for vgc in vgc_rows:
        app_id = str(vgc.get("application_id") or "").strip()
        name = str(vgc.get("name") or "").strip()
        if not app_id or not name:
            continue
        tx = lookup_transaction_for_vgc(name, tx_by_title)
        if tx:
            for key_fn in (norm_nintendo_title, match_nintendo_title_key):
                key = key_fn(str(tx.get("name") or ""))
                if key:
                    matched_tx_keys.add(key)
        merged.append(_hybrid_from_vgc(vgc, tx))

    for tx in tx_rows:
        name = str(tx.get("name") or "")
        keys = {norm_nintendo_title(name), match_nintendo_title_key(name)}
        keys.discard("")
        if not keys or keys & matched_tx_keys:
            continue
        matched_tx_keys |= keys
        merged.append(_hybrid_from_tx_only(tx))

    return finalize_nintendo_library_rows(merged)
