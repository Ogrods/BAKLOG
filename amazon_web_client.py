"""Prime Gaming claims via Luna (browser session replay).

Reads ``data.claims.claims[]`` from Luna GraphQL responses after the user signs in
on Connections (persistent profile at ``cache/auth/profiles/amazon_web``).

Filter (codeless / Amazon-fulfilled only):
- Drop claims with ``destinationAccountType`` in a known external launcher set
  (EPIC, STEAM, GOG, …) — these are redemption-key giveaways.
- Drop claims with any redemption/code field populated.
- Keep claims with a title and no external destination (Amazon Games delivery).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from auth.secrets import profile_dir

LUNA_CLAIMS_URL = "https://luna.amazon.com/claims/my-collection"
PROFILE_KEY = "amazon_web"

# External launcher targets from Prime Gaming key drops (user DevTools sample: EPIC).
_EXTERNAL_DESTINATION_TYPES = frozenset({
    "EPIC",
    "STEAM",
    "GOG",
    "UBISOFT",
    "BATTLENET",
    "BLIZZARD",
    "ORIGIN",
    "EA",
    "XBOX",
    "MICROSOFT",
    "NINTENDO",
    "RIOT",
    "ROCKSTAR",
    "BETHESDA",
    "HUMBLE",
    "ITCH",
})

_CODE_FIELD_NAMES = (
    "redemptionCode",
    "gameCode",
    "claimCode",
    "activationCode",
    "code",
)

_IMAGE_FIELD_CANDIDATES = (
    "imageUrl",
    "productImageUrl",
    "iconUrl",
    "thumbnailUrl",
    "boxArtUrl",
)

_DATE_FIELD_CANDIDATES = (
    "claimDate",
    "orderDate",
    "purchaseDate",
    "createdDate",
    "fulfillmentDate",
)


class AmazonWebAuthError(Exception):
    """Prime Gaming web session could not be read."""


class AmazonWebError(Exception):
    """Prime Gaming claims could not be parsed."""


def claims_visible_in_body(body: str) -> bool:
    return try_parse_claims_from_text(body) is not None


def try_parse_claims_from_text(body: str) -> list[dict[str, Any]] | None:
    """Return claims list if *body* is JSON with ``data.claims.claims``."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return extract_claims_list(data)


def extract_claims_list(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    claims_root = data.get("claims")
    if isinstance(claims_root, dict):
        items = claims_root.get("claims")
        if isinstance(items, list):
            return [c for c in items if isinstance(c, dict)]
    if isinstance(claims_root, list):
        return [c for c in claims_root if isinstance(c, dict)]
    return None


def _has_redemption_code(claim: dict[str, Any]) -> bool:
    for key in _CODE_FIELD_NAMES:
        val = claim.get(key)
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            return True
        if val:
            return True
    return False


def is_codeless_claim(claim: dict[str, Any]) -> bool:
    """True when the claim is Amazon-fulfilled (not an external key drop)."""
    title = (claim.get("itemTitle") or claim.get("title") or "").strip()
    if not title:
        return False
    dest_type = (claim.get("destinationAccountType") or "").strip().upper()
    if dest_type in _EXTERNAL_DESTINATION_TYPES:
        return False
    if _has_redemption_code(claim):
        return False
    state = (claim.get("orderState") or "").strip().upper()
    if state in ("CANCELLED", "CANCELED", "EXPIRED", "REVOKED"):
        return False
    return True


def _pick_image(claim: dict[str, Any]) -> str | None:
    for key in _IMAGE_FIELD_CANDIDATES:
        url = claim.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _pick_date(claim: dict[str, Any]) -> str | None:
    for key in _DATE_FIELD_CANDIDATES:
        raw = claim.get(key)
        if not raw:
            continue
        if isinstance(raw, str):
            if "T" in raw:
                return raw.split("T")[0]
            return raw[:10] if len(raw) >= 10 else raw
    return None


def claim_to_record(claim: dict[str, Any]) -> dict[str, Any] | None:
    if not is_codeless_claim(claim):
        return None
    title = (claim.get("itemTitle") or claim.get("title") or "").strip()
    product_id = (
        claim.get("itemId")
        or claim.get("offerId")
        or claim.get("orderId")
    )
    if not product_id:
        return None
    product_id = str(product_id)
    icon = _pick_image(claim)
    release = _pick_date(claim)
    store_url = f"https://www.amazon.com/s?k={quote(title)}&i=videogames"
    return {
        "amazon_product_id": product_id,
        "amazon_entitlement_id": claim.get("orderId"),
        "amazon_adg_id": None,
        "name": title,
        "asin": claim.get("productAsin") or claim.get("asin"),
        "product_sku": None,
        "product_line": "prime_claim",
        "header_image": icon,
        "library_image": icon,
        "genres": [],
        "release_date": release,
        "last_played": None,
        "store_url": store_url,
        "publisher": None,
        "prime_claim_order_state": claim.get("orderState"),
    }


def filter_codeless_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for claim in claims:
        rec = claim_to_record(claim)
        if not rec:
            continue
        pid = rec["amazon_product_id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        records.append(rec)
    return sorted(records, key=lambda r: r["name"].lower())


def sniff_claims(
    *,
    timeout_s: int = 60,
    dump_path: Path | str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Replay saved browser profile; return (raw_claims, codeless_records)."""
    from auth.cdp_browser import launch_persistent_profile

    profile = profile_dir(PROFILE_KEY)
    if not profile.is_dir():
        raise AmazonWebAuthError(
            "No saved Prime Gaming web profile. "
            "Open Connections and connect “Amazon (Prime Gaming, web)” first."
        )

    raw_claims: list[dict[str, Any]] = []
    captured: dict[str, bool] = {"done": False}

    def on_response(resp: Any) -> None:
        if captured["done"]:
            return
        try:
            status = getattr(resp, "status", 0)
            if status != 200:
                return
            url = (getattr(resp, "url", None) or "").lower()
            if "graphql" not in url:
                return
            body = resp.text()
            items = try_parse_claims_from_text(body)
            if items:
                raw_claims.clear()
                raw_claims.extend(items)
                captured["done"] = True
        except Exception:
            pass

    with launch_persistent_profile(str(profile), headless=True) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)
        try:
            page.goto(LUNA_CLAIMS_URL, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except Exception:
            pass
        deadline = time.time() + timeout_s
        while time.time() < deadline and not captured["done"]:
            page.wait_for_timeout(500)

    if dump_path is not None:
        path = Path(dump_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "url": LUNA_CLAIMS_URL,
                    "raw_claim_count": len(raw_claims),
                    "raw_claims": raw_claims,
                    "codeless_count": len(filter_codeless_claims(raw_claims)),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if not raw_claims:
        raise AmazonWebAuthError(
            "Could not capture Prime Gaming claims — session may have expired. "
            "Reconnect “Amazon (Prime Gaming, web)” on Connections."
        )

    return raw_claims, filter_codeless_claims(raw_claims)


class AmazonWebClient:
    def get_library_records(self) -> list[dict]:
        _raw, records = sniff_claims()
        return records
