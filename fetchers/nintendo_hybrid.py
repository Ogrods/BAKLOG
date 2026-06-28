import re
from collections import defaultdict
from urllib.parse import quote

from shared.library_noise import edition_title_join_key, is_nintendo_noise_row, maybe_tag_library_noise_row

_TRADEMARK_RE = re.compile("[™®©]")
_PUNCT_RE = re.compile("[^\\w\\s]+", re.UNICODE)
_DELUXE_MARKERS = ("digital deluxe", "deluxe edition", "gold edition", "ultimate edition")


def clean_nintendo_title(name):
    text = _TRADEMARK_RE.sub("", name or "")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def norm_nintendo_title(name):
    return clean_nintendo_title(name).lower()


def match_nintendo_title_key(name):
    return edition_title_join_key(name)


def nintendo_store_url(application_id, name):
    app = str(application_id or "").strip()
    if len(app) >= 8:
        return f"https://www.nintendo.com/us/store/products/game/{app}/"
    safe_name = quote((name or "").strip())
    return f"https://www.nintendo.com/us/store/products/{safe_name}/"


def index_existing_rows(existing):
    by_title = {}
    by_app_id = {}
    by_nintendo_id = {}
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
    return (by_title, by_app_id, by_nintendo_id)


def find_existing_row(item, *, existing, by_title, by_app_id, by_nintendo_id):
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


def index_transactions_by_title(tx_rows):
    by_title = {}
    for tx in tx_rows:
        name = str(tx.get("name") or "")
        for key in {norm_nintendo_title(name), match_nintendo_title_key(name)}:
            if key and key not in by_title:
                by_title[key] = tx
    return by_title


def lookup_transaction_for_vgc(vgc_name, tx_by_title):
    for key_fn in (norm_nintendo_title, match_nintendo_title_key):
        tx = tx_by_title.get(key_fn(vgc_name))
        if tx:
            return tx
    return None


def _merge_tags(*tag_lists):
    out = []
    for tags in tag_lists:
        if not tags:
            continue
        for tag in tags:
            if tag and tag not in out:
                out.append(tag)
    return out


def _hybrid_from_vgc(vgc, tx):
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


def _hybrid_from_tx_only(tx):
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


def is_nintendo_playable_game(item):
    return not is_nintendo_noise_row(item)


def dedupe_deluxe_edition_rows(rows):
    by_base = defaultdict(list)
    for row in rows:
        by_base[match_nintendo_title_key(str(row.get("name") or ""))].append(row)
    out = []
    for group in by_base.values():
        if len(group) == 1:
            out.append(group[0])
            continue

        def _rank(row):
            name_l = norm_nintendo_title(str(row.get("name") or ""))
            deluxe = any((marker in name_l for marker in _DELUXE_MARKERS))
            return (deluxe, row.get("ownership_source") != "both", not row.get("application_id"))

        group.sort(key=_rank)
        out.append(group[0])
    return out


def finalize_nintendo_library_rows(rows):
    tagged = []
    for row in rows:
        merged = dict(row)
        maybe_tag_library_noise_row(merged, "nintendo")
        tagged.append(merged)
    return dedupe_deluxe_edition_rows(tagged)


def merge_vgc_with_transactions(vgc_rows, tx_rows):
    tx_by_title = index_transactions_by_title(tx_rows)
    matched_tx_keys = set()
    merged = []
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
