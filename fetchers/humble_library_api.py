"""Pure parsers for Humble's redesigned /home/library Next.js RSC + actions.

No browser I/O here - callers fetch bodies (usually via in-page ``fetch``) and
pass the text in. Keeps ``fetch_humble.py`` under the module-size budget.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

# Last-known-good Next.js server action id for filterUserLibrary. Prefer runtime
# discovery from the /home/library client bundle; accept any parseable library
# payload when the hash rotates on a Humble deploy.
FILTER_USER_LIBRARY_ACTION = "607286a6c5956a391ffaab6aaf6d0d1e526e8034dd"
_FILTER_USER_LIBRARY_ACTION_RE = re.compile(
    r"""["']([a-f0-9]{40,44})["'].{0,160}?filterUserLibrary""",
    re.DOTALL,
)

LIBRARY_URL = "https://www.humblebundle.com/home/library"
# Live Next-Router-State-Tree from /home/library filterUserLibrary POSTs
# (no trailing null,null,true; three null,null,8 levels before 24).
_LIBRARY_ROUTER_STATE_TREE = (
    '["",{"children":["(default)",{"children":["(account)",{"children":["home",'
    '{"children":["library",{"children":["__PAGE__",{},null,null,0]},null,null,4]}'
    ",null,null,8]},null,null,8]},null,null,8]},null,null,24]"
)

_GAME_KEY_TYPES = frozenset({
    "steam", "origin", "uplay", "ubisoft", "epic", "gog", "battlenet", "external",
})
_NONGAME_PRODUCT_TYPES = frozenset({
    "ebook", "audiobook", "comic", "software", "soundtrack", "asmjs", "video",
})
_KEY_TYPE_SUFFIXES = (
    "_steam", "_gog", "_epic", "_origin", "_uplay", "_ubisoft", "_battlenet",
    "_external", "_download", "_drm_free",
)

# Empty previous-state blob accepted by filterUserLibrary (verified live).
EMPTY_LIBRARY_ACTION_STATE = (
    '[{"results":[],"pagination":{"page":1,"totalPages":1,"totalDocs":0},'
    '"success":true},"$K1"]'
)


def prev_state_from_action_body(text: str) -> str | None:
    """Build useActionState field ``0`` from a filterUserLibrary flight body.

    Next.js expects ``[{...payload},\"$K1\"]`` with the **raw** payload JSON.
    Parsing then re-stringifying drops ``$undefined`` and stalls pagination.
    """
    if not text:
        return None
    raw_payload: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        row_id, rest = line.split(":", 1)
        if not row_id:
            continue
        rest = rest.strip()
        if not rest.startswith("{") or '"results"' not in rest:
            continue
        # Prefer the standard action result row id ``1``.
        if row_id == "1":
            raw_payload = rest
            break
        if raw_payload is None:
            raw_payload = rest
    if not raw_payload:
        return None
    return f'[{raw_payload},"$K1"]'


@dataclass
class LibraryItem:
    machine_name: str
    name: str
    image_url: str | None
    store_url: str
    gamekey: str
    redeemed: bool | None
    steam_app_id: str | None
    expired: bool = False
    delivery_type: str = ""


def discover_action_id(text: str) -> str | None:
    """Extract the current filterUserLibrary Next.js action id from JS/HTML."""
    if not text or "filterUserLibrary" not in text:
        return None
    m = _FILTER_USER_LIBRARY_ACTION_RE.search(text)
    return m.group(1) if m else None


def _replace_undefined(text: str) -> str:
    return text.replace('"$undefined"', "null").replace("'$undefined'", "null")


def parse_flight_rows(text: str) -> dict[str, Any]:
    """Parse a Next.js flight / RSC body into ``{row_id: value}``.

    Handles ``<id>:<json>`` rows and ``<id>:T<hexlen>,<text>`` text chunks.
    Values that fail JSON decode are kept as raw strings.
    """
    out: dict[str, Any] = {}
    if not text:
        return out
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        row_id, rest = line.split(":", 1)
        if not row_id:
            continue
        rest = rest.strip()
        if rest.startswith("T") and "," in rest[:24]:
            # Text chunk: T<hexlen>,<payload>
            try:
                hexlen, payload = rest[1:].split(",", 1)
                int(hexlen, 16)
                out[row_id] = payload
                continue
            except ValueError:
                pass
        cleaned = _replace_undefined(rest)
        if cleaned[:1] in "{[\"0123456789-ntf":
            try:
                out[row_id] = json.loads(cleaned)
                continue
            except json.JSONDecodeError:
                pass
        out[row_id] = rest
    return out


def looks_like_filter_user_library_payload(obj: Any) -> bool:
    """True when ``obj`` matches the filterUserLibrary ``{results, ...}`` shape."""
    if not isinstance(obj, dict) or not isinstance(obj.get("results"), list):
        return False
    if "pagination" in obj or "success" in obj:
        return True
    return bool(obj["results"])


def extract_library_page(text: str) -> dict[str, Any] | None:
    """Pull ``{results, pagination, success}`` out of a Next.js action / RSC body."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{") and '"results"' in stripped:
        try:
            obj = json.loads(_replace_undefined(stripped))
            if looks_like_filter_user_library_payload(obj):
                return obj
        except json.JSONDecodeError:
            pass

    rows = parse_flight_rows(text)
    best: dict[str, Any] | None = None
    for val in rows.values():
        if looks_like_filter_user_library_payload(val):
            if best is None or len(val["results"]) >= len(best.get("results") or []):
                best = val
    if best is not None:
        return best

    # Fallback: scan for embedded JSON objects (older / partial flight shapes).
    decoder = json.JSONDecoder()
    cleaned = _replace_undefined(text)
    for m in re.finditer(r"\"results\"\s*:\s*\[", cleaned):
        start = cleaned.rfind("{", 0, m.start())
        if start < 0:
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned, start)
        except json.JSONDecodeError:
            continue
        if looks_like_filter_user_library_payload(obj):
            if best is None or len(obj["results"]) >= len(best.get("results") or []):
                best = obj
    return best


def extract_bundle_items(rsc_text: str) -> list[dict[str, Any]]:
    """Order list from RSC ``GET /home/library`` (``bundleItems``)."""
    if not rsc_text:
        return []
    rows = parse_flight_rows(rsc_text)
    for val in rows.values():
        if isinstance(val, dict) and isinstance(val.get("bundleItems"), list):
            return [x for x in val["bundleItems"] if isinstance(x, dict)]
    # Embedded search
    cleaned = _replace_undefined(rsc_text)
    idx = cleaned.find('"bundleItems"')
    if idx < 0:
        return []
    start = cleaned.rfind("{", 0, idx)
    if start < 0:
        return []
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned, start)
    except json.JSONDecodeError:
        return []
    items = obj.get("bundleItems") if isinstance(obj, dict) else None
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def order_entitlements(rsc_text: str) -> list[dict[str, Any]]:
    """Flatten keys + downloads from RSC ``GET /home/library/<orderId>``."""
    if not rsc_text:
        return []
    rows = parse_flight_rows(rsc_text)
    user_item: dict[str, Any] | None = None
    for val in rows.values():
        if not isinstance(val, dict):
            continue
        if isinstance(val.get("userLibraryItem"), dict):
            user_item = val["userLibraryItem"]
            break
        if isinstance(val.get("entitlements"), dict) and (
            val.get("entitlements", {}).get("keys") is not None
            or val.get("entitlements", {}).get("downloads") is not None
        ):
            user_item = val
            break
    if user_item is None:
        cleaned = _replace_undefined(rsc_text)
        idx = cleaned.find('"userLibraryItem"')
        if idx >= 0:
            start = cleaned.find("{", idx)
            if start >= 0:
                try:
                    user_item, _ = json.JSONDecoder().raw_decode(cleaned, start)
                except json.JSONDecodeError:
                    user_item = None
    if not isinstance(user_item, dict):
        return []
    ents = user_item.get("entitlements")
    if not isinstance(ents, dict):
        return []
    out: list[dict[str, Any]] = []
    order_id = str(
        user_item.get("productEntitlementId")
        or user_item.get("id")
        or ""
    ).strip()
    order_title = str(user_item.get("title") or user_item.get("subTitle") or "").strip()
    for key in ("keys", "downloads"):
        for ent in ents.get(key) or []:
            if not isinstance(ent, dict):
                continue
            row = dict(ent)
            if order_id and not row.get("productEntitlementId"):
                row["productEntitlementId"] = order_id
            if order_title and not row.get("subTitle"):
                row["subTitle"] = order_title
            if not row.get("itemType"):
                row["itemType"] = "content-entitlement"
            out.append(row)
    return out


def _iter_download_platform_rows(obj: dict) -> list[dict]:
    """Yield platform rows from nested entitlements or a flat download entitlement."""
    rows: list[dict] = []
    ents = obj.get("entitlements") if isinstance(obj.get("entitlements"), dict) else {}
    candidates = []
    if isinstance(ents, dict):
        candidates.extend(ents.get("downloads") or [])
    # Flat download entitlement from order RSC.
    if obj.get("type") == "download_drm_free" or isinstance(obj.get("downloads"), list):
        candidates.append(obj)
    for dl in candidates:
        if not isinstance(dl, dict):
            continue
        platforms = dl.get("downloads")
        if isinstance(platforms, list):
            rows.extend(p for p in platforms if isinstance(p, dict))
    return rows


def library_result_is_game(obj: dict) -> bool:
    product_type = str(obj.get("productType") or obj.get("type") or "").strip().lower()
    if product_type in _NONGAME_PRODUCT_TYPES:
        return False
    if product_type in _GAME_KEY_TYPES:
        return True
    if product_type == "download_drm_free":
        saw_platform = False
        for p in _iter_download_platform_rows(obj):
            saw_platform = True
            plat = str(p.get("platform") or "").lower()
            if plat in {"windows", "mac", "linux", "android"}:
                return True
            if plat in _NONGAME_PRODUCT_TYPES:
                return False
        if saw_platform:
            return False
        # No platform rows: keep unless the title clearly names a non-game.
    title = str(obj.get("title") or obj.get("human_name") or "").lower()
    if any(tok in title for tok in ("soundtrack only", "ebook", "audiobook", "comic book")):
        return False
    if product_type in {"", "bundle", "storefront", "content-entitlement", "download_drm_free"}:
        return True
    return product_type not in _NONGAME_PRODUCT_TYPES


def steam_app_from_library_result(obj: dict) -> str | None:
    ents = obj.get("entitlements") if isinstance(obj.get("entitlements"), dict) else {}
    for key in ("keys", "downloads"):
        for ent in ents.get(key) or []:
            if not isinstance(ent, dict):
                continue
            for field in ("steam_app_id", "steam_appid", "steamAppId"):
                val = ent.get(field)
                if val is not None and str(val).strip():
                    return str(val).strip()
    for field in ("steam_app_id", "steam_appid", "steamAppId"):
        val = obj.get(field)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _redeemed_from_result(obj: dict) -> bool | None:
    if isinstance(obj.get("redeemed"), bool):
        return obj["redeemed"]
    ents = obj.get("entitlements") if isinstance(obj.get("entitlements"), dict) else {}
    keys = list(ents.get("keys") or []) if isinstance(ents, dict) else []
    # Flat key row (order-detail fallback) looks like a key itself.
    if obj.get("keyIntegrationId") or obj.get("redemptionData") is not None:
        keys = [obj]
    if not keys:
        return None
    for key in keys:
        if not isinstance(key, dict):
            continue
        if key.get("redeemedAt"):
            return True
        rd = key.get("redemptionData")
        if isinstance(rd, dict) and (
            rd.get("keyFormatted") or rd.get("externalAccountName")
        ):
            return True
        if key.get("redeemed") is True:
            return True
    # Had keys but none redeemed.
    return False


def _expired_from_result(obj: dict) -> bool:
    if obj.get("expired") is True:
        return True
    ents = obj.get("entitlements") if isinstance(obj.get("entitlements"), dict) else {}
    for key in ("keys", "downloads"):
        for ent in (ents.get(key) or []) if isinstance(ents, dict) else []:
            if isinstance(ent, dict) and ent.get("expired") is True:
                return True
    return False


def store_url_for_item(content_id: str, steam_app_id: str | None) -> str:
    if steam_app_id:
        return f"https://store.steampowered.com/app/{steam_app_id}"
    cid = (content_id or "").strip()
    if cid:
        return f"https://www.humblebundle.com/home/library/content/{quote(cid, safe='')}"
    return "https://www.humblebundle.com/home/library"


def item_from_result(obj: dict, *, include_nongames: bool = False) -> LibraryItem | None:
    """Map one filterUserLibrary / entitlement row into a LibraryItem.

    Identity is ``contentId`` (stable per-game slug). ``productEntitlementId`` is
    the parent order id and must not be used as the row key.
    """
    if not isinstance(obj, dict):
        return None
    if not include_nongames and not library_result_is_game(obj):
        return None
    content_id = str(obj.get("contentId") or "").strip()
    ent_id = str(obj.get("id") or "").strip()
    machine = content_id or ent_id
    name = str(obj.get("title") or obj.get("human_name") or machine or "").strip()
    if not machine and not name:
        return None
    if not machine:
        machine = name
    image = None
    for key in ("image", "icon", "header_image", "library_image", "cover"):
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            image = val
            break
    steam_id = steam_app_from_library_result(obj)
    redeemed = _redeemed_from_result(obj)
    delivery = str(obj.get("type") or obj.get("keyIntegrationId") or "").strip().lower()
    order_id = str(
        obj.get("productEntitlementId")
        or obj.get("orderId")
        or obj.get("gamekey")
        or ""
    ).strip()
    return LibraryItem(
        machine_name=machine,
        name=name or machine,
        image_url=image,
        store_url=store_url_for_item(content_id or ent_id, steam_id),
        gamekey=order_id or machine,
        redeemed=redeemed,
        steam_app_id=steam_id,
        expired=_expired_from_result(obj),
        delivery_type=delivery,
    )


def strip_key_type_suffix(content_id: str) -> str:
    low = (content_id or "").lower()
    for suf in _KEY_TYPE_SUFFIXES:
        if low.endswith(suf):
            return content_id[: -len(suf)]
    return content_id


def norm_title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def match_cached_row(
    item: LibraryItem,
    by_id: dict[str, dict],
    by_title: dict[str, dict] | None = None,
) -> dict | None:
    """Find a prior catalog row for ``item`` across id migrations."""
    if item.machine_name in by_id:
        return by_id[item.machine_name]
    stripped = strip_key_type_suffix(item.machine_name)
    if stripped and stripped != item.machine_name and stripped in by_id:
        return by_id[stripped]
    # Also try adding common suffixes when cache has the bare slug.
    for suf in ("_steam", "_gog", "_epic"):
        alt = f"{item.machine_name}{suf}"
        if alt in by_id:
            return by_id[alt]
    if by_title:
        tk = norm_title_key(item.name)
        if tk and tk in by_title:
            return by_title[tk]
    return None


def library_action_form_fields(
    *,
    page: int,
    limit: int,
    cursor: int,
    request_id: str,
    prev_state: str = EMPTY_LIBRARY_ACTION_STATE,
) -> dict[str, str]:
    """Form fields for ``POST /home/library`` filterUserLibrary."""
    return {
        "_1_requestId": request_id,
        "_1_query": "",
        "_1_sort": "mostRecent",
        "_1_cursor": str(cursor),
        "_1_page": str(page),
        "_1_limit": str(limit),
        "_1_hideRevealed": "false",
        "_1_hideExpired": "false",
        "_1_dateExpires": "",
        "0": prev_state,
    }


def library_action_headers(action_id: str) -> dict[str, str]:
    # Prefer building encodeURIComponent(tree) in-page (see fetch_humble).
    # This helper remains for tests / callers that already URI-encode once.
    return {
        "Accept": "text/x-component",
        "Next-Action": action_id,
        "Next-Router-State-Tree": quote(_LIBRARY_ROUTER_STATE_TREE, safe=""),
    }


def rsc_headers() -> dict[str, str]:
    return {"RSC": "1", "Accept": "text/x-component"}
