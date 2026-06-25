"""Merge Nintendo Virtual Game Cards with eShop transaction rows."""

from __future__ import annotations

from typing import Any


def norm_nintendo_title(name: str) -> str:
    return " ".join((name or "").lower().split())


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
        return by_title.get(title_key)
    return None


def _hybrid_from_tx(tx: dict[str, Any], vgc: dict[str, Any] | None) -> dict[str, Any]:
    app_id = str(vgc.get("application_id") or "").strip() if vgc else ""
    tx_id = str(tx.get("id") or tx.get("nintendo_id") or "")
    row_id = app_id or tx_id
    tags = list(tx.get("tags") or [])
    if vgc and vgc.get("is_dlc") and "dlc" not in tags:
        tags.append("dlc")
    platform = (vgc or {}).get("platform") or tx.get("device_type")
    icon = (vgc or {}).get("icon_url")
    return {
        "name": tx["name"],
        "id": row_id,
        "application_id": app_id or None,
        "nintendo_id": tx_id or None,
        "vgc_id": (vgc or {}).get("vgc_id"),
        "purchase_date": tx.get("purchase_date"),
        "device_type": tx.get("device_type"),
        "content_type": tx.get("content_type"),
        "tags": tags,
        "nintendo_platform": platform,
        "icon_url": icon,
        "publisher": (vgc or {}).get("publisher"),
        "ownership_source": "both" if vgc and app_id else "transaction",
    }


def _hybrid_from_vgc(vgc: dict[str, Any]) -> dict[str, Any]:
    app_id = str(vgc.get("application_id") or vgc.get("vgc_id") or "").strip()
    tags = ["dlc"] if vgc.get("is_dlc") else []
    return {
        "name": vgc["name"],
        "id": app_id,
        "application_id": app_id or None,
        "nintendo_id": None,
        "vgc_id": vgc.get("vgc_id"),
        "purchase_date": None,
        "device_type": None,
        "content_type": None,
        "tags": tags,
        "nintendo_platform": vgc.get("platform"),
        "icon_url": vgc.get("icon_url"),
        "publisher": vgc.get("publisher"),
        "ownership_source": "vgc",
    }


def merge_vgc_with_transactions(
    vgc_rows: list[dict[str, Any]],
    tx_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union VGC entitlements with eShop transactions, keyed on application_id when matched."""
    vgc_by_title: dict[str, dict[str, Any]] = {}
    for row in vgc_rows:
        title_key = norm_nintendo_title(str(row.get("name") or ""))
        if title_key and title_key not in vgc_by_title:
            vgc_by_title[title_key] = row

    matched_app_ids: set[str] = set()
    merged: list[dict[str, Any]] = []

    for tx in tx_rows:
        title_key = norm_nintendo_title(str(tx.get("name") or ""))
        vgc = vgc_by_title.get(title_key)
        item = _hybrid_from_tx(tx, vgc)
        app_id = str(item.get("application_id") or "").strip()
        if app_id:
            matched_app_ids.add(app_id)
        merged.append(item)

    for vgc in vgc_rows:
        app_id = str(vgc.get("application_id") or "").strip()
        if not app_id or app_id in matched_app_ids:
            continue
        name = str(vgc.get("name") or "").strip()
        if not name:
            continue
        matched_app_ids.add(app_id)
        merged.append(_hybrid_from_vgc(vgc))

    return merged
