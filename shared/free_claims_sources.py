"""Shared helpers for auto-sourced free-claim discovery and merge."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

EPIC_FREE_GAMES_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=en-US&country=US&allowCountries=US"
)
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways?platform=pc&type=game"
ITAD_GIVEAWAYS_RSS = "https://isthereanydeal.com/feeds/US/giveaways.rss"
GAMERPOWER_ATTRIBUTION = "GamerPower.com"

ITAD_SKIP_KEYWORDS = ("bundle", "beta", "dlc", "loot", " key")

SOURCE_PRECEDENCE = {"epic": 0, "gamerpower": 1, "itad": 2}


def norm_title(title: str) -> str:
    """Normalize a game title for dedup/merge keys."""
    base = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return re.sub(r"\s+", " ", base)


def merge_key(item: dict) -> str:
    item_id = str(item.get("id") or "").strip()
    if item_id:
        return f"id:{item_id}"
    return f"title:{norm_title(str(item.get('title') or ''))}"


def merge_manual_and_auto(manual_items: list[dict], auto_items: list[dict]) -> list[dict]:
    """Merge manual + auto items; manual entries win on duplicate keys."""
    seen: set[str] = set()
    merged: list[dict] = []
    for raw in manual_items:
        if not isinstance(raw, dict):
            continue
        key = merge_key(raw)
        seen.add(key)
        seen.add(f"title:{norm_title(str(raw.get('title') or ''))}")
        merged.append(raw)
    for raw in auto_items:
        if not isinstance(raw, dict):
            continue
        title_key = f"title:{norm_title(str(raw.get('title') or ''))}"
        key = merge_key(raw)
        if key in seen or title_key in seen:
            continue
        seen.add(key)
        seen.add(title_key)
        merged.append(raw)
    return merged


def dedup_claim_items(items: list[dict]) -> list[dict]:
    """Dedup auto items by normalized title; lower SOURCE_PRECEDENCE wins."""
    by_title: dict[str, dict] = {}
    for item in items:
        title_key = norm_title(str(item.get("title") or ""))
        if not title_key:
            continue
        source = str(item.get("source") or "")
        rank = SOURCE_PRECEDENCE.get(source, 99)
        existing = by_title.get(title_key)
        if existing is None:
            by_title[title_key] = item
            continue
        existing_rank = SOURCE_PRECEDENCE.get(str(existing.get("source") or ""), 99)
        if rank < existing_rank:
            by_title[title_key] = item
    return list(by_title.values())


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _epic_page_slug(element: dict) -> str | None:
    mappings = element.get("offerMappings") or []
    if mappings and mappings[0].get("pageSlug"):
        return str(mappings[0]["pageSlug"])
    catalog = element.get("catalogNs") or {}
    ns_mappings = catalog.get("mappings") or []
    if ns_mappings and ns_mappings[0].get("pageSlug"):
        return str(ns_mappings[0]["pageSlug"])
    product_slug = element.get("productSlug")
    if product_slug:
        return str(product_slug)
    url_slug = element.get("urlSlug")
    if url_slug:
        return str(url_slug)
    return None


def _epic_header_image(element: dict) -> str | None:
    for preferred in ("OfferImageWide", "Thumbnail", "OfferImageTall"):
        for img in element.get("keyImages") or []:
            if img.get("type") == preferred and img.get("url"):
                return str(img["url"])
    return None


def _active_epic_free_offer(element: dict, *, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(UTC)
    promotions = element.get("promotions") or {}
    for group in promotions.get("promotionalOffers") or []:
        for offer in group.get("promotionalOffers") or []:
            discount = (offer.get("discountSetting") or {}).get("discountPercentage")
            if discount != 0:
                continue
            start = _parse_iso_dt(offer.get("startDate"))
            end = _parse_iso_dt(offer.get("endDate"))
            if start and now < start:
                continue
            if end and now > end:
                continue
            return offer
    return None


def parse_epic_element(element: dict, *, now: datetime | None = None) -> dict | None:
    offer = _active_epic_free_offer(element, now=now)
    if not offer:
        return None
    slug = _epic_page_slug(element)
    if not slug:
        return None
    title = str(element.get("title") or "").strip()
    if not title:
        return None
    return {
        "id": f"epic-{slug}",
        "store": "epic",
        "title": title,
        "claim_url": f"https://store.epicgames.com/en-US/p/{slug}",
        "ends_at": _to_iso_z(_parse_iso_dt(offer.get("endDate"))),
        "header_image": _epic_header_image(element),
        "blurb": None,
        "source": "epic",
    }


def parse_epic_payload(payload: dict, *, now: datetime | None = None) -> list[dict]:
    elements = (
        payload.get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )
    items: list[dict] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        parsed = parse_epic_element(element, now=now)
        if parsed:
            items.append(parsed)
    return items


def platforms_to_store(platforms: str) -> str:
    text = (platforms or "").lower()
    if "steam" in text:
        return "steam"
    if "epic" in text:
        return "epic"
    if "gog" in text:
        return "gog"
    if "itch" in text:
        return "itch"
    if "ubisoft" in text:
        return "ubisoft"
    if "humble" in text:
        return "humble"
    return "other"


def parse_gamerpower_item(raw: dict) -> dict | None:
    if str(raw.get("status") or "").lower() != "active":
        return None
    gp_id = raw.get("id")
    title = str(raw.get("title") or "").strip()
    claim_url = str(raw.get("open_giveaway_url") or raw.get("open_giveaway") or "").strip()
    if gp_id is None or not title or not claim_url:
        return None
    end_dt = _parse_iso_dt(str(raw.get("end_date") or ""))
    return {
        "id": f"gamerpower-{gp_id}",
        "store": platforms_to_store(str(raw.get("platforms") or "")),
        "title": title,
        "claim_url": claim_url,
        "ends_at": _to_iso_z(end_dt),
        "header_image": raw.get("image") or raw.get("thumbnail"),
        "blurb": raw.get("description"),
        "source": "gamerpower",
    }


def parse_gamerpower_payload(payload: list[Any]) -> list[dict]:
    items: list[dict] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        parsed = parse_gamerpower_item(raw)
        if parsed:
            items.append(parsed)
    return items


def should_skip_itad_title(title: str) -> bool:
    lower = (title or "").lower()
    return any(keyword in lower for keyword in ITAD_SKIP_KEYWORDS)


def _itad_store_from_text(text: str) -> str:
    lower = (text or "").lower()
    for store, needles in (
        ("steam", ("steam",)),
        ("epic", ("epic",)),
        ("gog", ("gog",)),
        ("itch", ("itch.io", "itch")),
        ("ubisoft", ("ubisoft",)),
        ("humble", ("humble",)),
    ):
        if any(n in lower for n in needles):
            return store
    return "other"


def parse_itad_rss(xml_text: str) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        if not title or not link:
            continue
        if should_skip_itad_title(title):
            continue
        digest = hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]
        items.append(
            {
                "id": f"itad-{digest}",
                "store": _itad_store_from_text(f"{title} {description}"),
                "title": title,
                "claim_url": link,
                "ends_at": None,
                "header_image": None,
                "blurb": description or None,
                "source": "itad",
            }
        )
    return items
