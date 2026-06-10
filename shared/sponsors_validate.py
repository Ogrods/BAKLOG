"""Sponsor feed schema validation (v1 items/placements + v2 ads/locations)."""

from __future__ import annotations

from typing import Any

# Sync pair: js/sponsored-deals.js AD_LOCATIONS, admin/admin.js, migrate_sponsors_v2.py
SPONSOR_AD_LOCATIONS: frozenset[str] = frozenset(
    {
        "dash-spotlight",
        "dash-feature-banner",
        "dash-coop-online",
        "dash-coop-couch",
        "dash-versus-rated",
        "dash-versus-fast",
        "dash-pick",
        "dash-house",
        "lib-pick",
        "lib-row",
        "lib-house",
        "wish-pick",
        "wish-row",
        "wish-deal-hero",
        "wish-deal-portrait",
        "wish-house",
        "deals-pick",
        "deals-row",
        "itch-pick",
        "itch-row",
        "itch-house",
        "claim-cards",
    }
)


def _validate_sponsor_creative(ad_id: str, item: Any) -> str | None:
    if not isinstance(item, dict):
        return f"ads[{ad_id}] must be an object"
    if not str(item.get("title") or "").strip():
        return f"ads[{ad_id}] missing title"
    url = item.get("url")
    if url is not None and str(url).strip():
        u = str(url).strip()
        if not (u.startswith("http://") or u.startswith("https://")):
            return f"ads[{ad_id}] url must start with http:// or https://"
    enabled = item.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        return f"ads[{ad_id}] enabled must be boolean"
    kind = item.get("kind")
    if kind is not None and str(kind).strip():
        k = str(kind).strip().lower()
        if k not in ("house", "sponsor"):
            return f"ads[{ad_id}] kind must be house or sponsor"
    cover = item.get("cover")
    if cover is not None and str(cover).strip():
        c = str(cover).strip()
        if not (
            c.startswith("http://")
            or c.startswith("https://")
            or (c.startswith("/") and not c.startswith("//"))
        ):
            return f"ads[{ad_id}] cover must be http(s) URL or same-origin path"
    return None


def _validate_sponsors_v2(doc: dict[str, Any]) -> str | None:
    ads = doc.get("ads")
    locations = doc.get("locations")
    if not isinstance(ads, dict):
        return "ads must be an object"
    if not isinstance(locations, dict):
        return "locations must be an object"
    for ad_id, item in ads.items():
        if not str(ad_id).strip():
            return "ads keys must be non-empty strings"
        err = _validate_sponsor_creative(str(ad_id), item)
        if err:
            return err
    for loc, ids in locations.items():
        loc_name = str(loc).strip().lower()
        if loc_name not in SPONSOR_AD_LOCATIONS:
            return f"locations contains unknown key: {loc}"
        if not isinstance(ids, list):
            return f"locations[{loc}] must be a list"
        for ref in ids:
            ref_id = str(ref).strip()
            if not ref_id:
                return f"locations[{loc}] contains empty id"
            if ref_id not in ads:
                return f"locations[{loc}] references unknown ad id: {ref_id}"
    return None


def _validate_sponsors_v1(doc: dict[str, Any]) -> str | None:
    items = doc.get("items")
    if not isinstance(items, list):
        return "items must be a list"
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"items[{i}] must be an object"
        for field in ("id", "title"):
            if not str(item.get(field) or "").strip():
                return f"items[{i}] missing {field}"
        err = _validate_sponsor_creative(str(item.get("id") or f"items[{i}]"), item)
        if err:
            return err.replace("ads[", "items[").replace(f"ads[{item.get('id')}]", f"items[{i}]")
        placements = item.get("placements")
        if placements is not None and placements != "":
            raw = placements if isinstance(placements, list) else str(placements).split(",")
            valid = {
                "deal-rail",
                "dash-deal-rail",
                "spotlight",
                "picks",
                "table",
                "dash-picks",
                "dash-feature-banner",
                "dash-versus",
                "coop-online",
                "coop-couch",
                "claimable",
            }
            for p in raw:
                name = str(p).strip().lower()
                if name and name not in valid:
                    return f"items[{i}] placements contains unknown value: {name}"
    return None


def validate_sponsors_payload(doc: dict[str, Any]) -> str | None:
    if doc.get("version") == 2:
        return _validate_sponsors_v2(doc)
    if "ads" in doc or "locations" in doc:
        return "mixed schema: set version to 2 for ads/locations payloads"
    return _validate_sponsors_v1(doc)
