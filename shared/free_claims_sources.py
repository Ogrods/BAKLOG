import hashlib
import re
from datetime import UTC, datetime
from xml.etree import ElementTree

from shared.steam_match import strip_giveaway_decorations

EPIC_FREE_GAMES_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
)
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways?platform=pc&type=game"
ITAD_GIVEAWAYS_RSS = "https://isthereanydeal.com/feeds/US/giveaways.rss"
GAMERPOWER_ATTRIBUTION = "GamerPower.com"
ITAD_SKIP_KEYWORDS = ("bundle", "beta", "dlc", "loot", " key")
SOURCE_PRECEDENCE = {"epic": 0, "gamerpower": 1, "itad": 2}
EPIC_MOBILE_STORE = "epic_mobile"


def is_epic_mobile_store(store):
    return str(store or "").strip().lower() == EPIC_MOBILE_STORE


def _is_safe_http_url(url):
    u = str(url or "").strip()
    return u.startswith("http://") or u.startswith("https://")


def normalize_claim_urls(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in ("ios", "android"):
        val = str(raw.get(key) or "").strip()
        if val and _is_safe_http_url(val):
            out[key] = val
    return out


def has_valid_claim_links(item):
    if is_epic_mobile_store(item.get("store")):
        return bool(normalize_claim_urls(item.get("claim_urls")))
    return _is_safe_http_url(str(item.get("claim_url") or ""))


def item_missing_link_fields(item):
    if is_epic_mobile_store(item.get("store")):
        if not normalize_claim_urls(item.get("claim_urls")):
            return ["claim_urls"]
        return []
    if not str(item.get("claim_url") or "").strip():
        return ["claim_url"]
    return []


CLAIM_ENRICH_FIELDS = ("header_image", "review_percent", "steam_appid", "genres", "blurb")


def carry_claim_enrichment(fresh, existing):
    if not existing:
        return fresh
    out = dict(fresh)
    for key in CLAIM_ENRICH_FIELDS:
        win_val = out.get(key)
        lose_val = existing.get(key)
        if key == "genres":
            if (not win_val or win_val == []) and isinstance(lose_val, list) and lose_val:
                out[key] = lose_val
            continue
        if (win_val is None or win_val == "") and lose_val not in (None, ""):
            out[key] = lose_val
    return out


def norm_title(title):
    stripped = strip_giveaway_decorations(str(title or ""))
    base = stripped.lower().replace("&", " and ").replace("+", " and ")
    base = re.sub("[^a-z0-9]+", " ", base).strip()
    return re.sub("\\s+", " ", base)


def claim_match_keys(item):
    keys = set()
    appid = item.get("steam_appid")
    if appid is not None:
        try:
            appid_int = int(appid)
            if appid_int:
                keys.add(f"appid:{appid_int}")
        except (TypeError, ValueError):
            pass
    title_norm = norm_title(str(item.get("title") or ""))
    if title_norm:
        keys.add(f"title:{title_norm}")
    return keys


def merge_key(item):
    item_id = str(item.get("id") or "").strip()
    if item_id:
        return f"id:{item_id}"
    return f"title:{norm_title(str(item.get('title') or ''))}"


def merge_manual_and_auto(manual_items, auto_items):
    seen = set()
    merged = []
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


def dedup_claim_items_by_id(items):
    by_key = {}
    anon = 0
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if item_id:
            key = item_id
        else:
            key = f"_anon:{anon}"
            anon += 1
        source = str(item.get("source") or "")
        rank = SOURCE_PRECEDENCE.get(source, 99)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            continue
        existing_rank = SOURCE_PRECEDENCE.get(str(existing.get("source") or ""), 99)
        if rank < existing_rank:
            by_key[key] = item
    return list(by_key.values())


def _parse_iso_dt(value):
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


def _to_iso_z(dt):
    if dt is None:
        return None
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _epic_page_slug(element):
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


def _epic_header_image(element):
    for preferred in ("OfferImageWide", "Thumbnail", "OfferImageTall"):
        for img in element.get("keyImages") or []:
            if img.get("type") == preferred and img.get("url"):
                return str(img["url"])
    return None


def _active_epic_free_offer(element, *, now=None):
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


def parse_epic_element(element, *, now=None):
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


def parse_epic_payload(payload, *, now=None):
    elements = payload.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
    items = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        parsed = parse_epic_element(element, now=now)
        if parsed:
            items.append(parsed)
    return items


def platforms_to_store(platforms):
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


def parse_gamerpower_item(raw):
    if str(raw.get("status") or "").lower() != "active":
        return None
    gp_id = raw.get("id")
    title = str(raw.get("title") or "").strip()
    claim_url = str(raw.get("open_giveaway_url") or raw.get("open_giveaway") or "").strip()
    if gp_id is None or not title or (not claim_url):
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


def parse_gamerpower_payload(payload):
    items = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        parsed = parse_gamerpower_item(raw)
        if parsed:
            items.append(parsed)
    return items


def should_skip_itad_title(title):
    lower = (title or "").lower()
    return any(keyword in lower for keyword in ITAD_SKIP_KEYWORDS)


def _itad_store_from_text(text):
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


def parse_itad_rss(xml_text):
    root = ElementTree.fromstring(xml_text)
    items = []
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
