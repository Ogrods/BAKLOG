"""Nintendo Virtual Game Cards (VGC) via accounts.nintendo.com portal.

Entitlements list (stable applicationId) complements eShop transaction history
in clients/nintendo_client.py (~2 year receipt window).
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

VGC_PORTAL_URL = (
    "https://accounts.nintendo.com/portal/vgcs/?sort=activated_date&order=desc"
)
VGC_PAGE_LIMIT = 300
DATA_JSON_RE = re.compile(r'<div id="data" data-json="(.*?)"', re.DOTALL)
STATE_JSON_RE = re.compile(r'<div id="state" data-json="(.*?)"', re.DOTALL)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_SIZE_PLACEHOLDER = "${size}"
_DEFAULT_ICON_SIZE = 256
_HEADER_ICON_SIZE = 512


def _parse_icon_sizes(sizes: Any) -> list[int]:
    if not isinstance(sizes, list):
        return []
    out: list[int] = []
    for raw in sizes:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _pick_icon_size(sizes: Any, *, prefer_large: bool = False) -> int:
    parsed = _parse_icon_sizes(sizes)
    if not parsed:
        return _HEADER_ICON_SIZE if prefer_large else _DEFAULT_ICON_SIZE
    viable = [s for s in parsed if s >= 128]
    pool = viable or parsed
    if prefer_large:
        return max(pool)
    return min(pool, key=lambda s: abs(s - _DEFAULT_ICON_SIZE))


def resolve_nintendo_icon_url(
    url: str | None,
    sizes: Any = None,
    *,
    prefer_large: bool = False,
) -> str | None:
    """Expand Nintendo atum CDN ``${size}`` placeholders to a real pixel size."""
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if _SIZE_PLACEHOLDER not in text:
        return text
    size = _pick_icon_size(sizes, prefer_large=prefer_large)
    return text.replace(_SIZE_PLACEHOLDER, str(size))

REGION_DEFAULTS: dict[str, dict[str, Any]] = {
    "US": {
        "country": "US",
        "shop_id": 1,
        "nas_language": "en-US",
        "language": "en",
    },
    "GB": {
        "country": "GB",
        "shop_id": 3,
        "nas_language": "en-GB",
        "language": "en",
    },
    "CA": {
        "country": "CA",
        "shop_id": 2,
        "nas_language": "en-CA",
        "language": "en",
    },
}

VGC_GRAPHQL_QUERY = """query getVgcs(
    $idToken: String!
    $country: CountryCode!
    $language: LanguageCode!
    $shopId: Int!
    $limit: Int!
    $nasLanguage: String!
    $offset: Int!
    $order: RequestableVgcViewOrder!
    $sortBy: RequestableVgcViewSortBy!
    $vgcViewType: VgcViewTypeInput
    $vgcViewStatus: VgcViewStatusInput
  ) @inContext(country: $country, language: $language, shopId: $shopId) {
    account {
      vgc {
        vgcViews(
          idToken: $idToken,
          limit: $limit,
          nasLanguage: $nasLanguage,
          offset: $offset,
          order: $order,
          sortBy: $sortBy,
          isHidden: false,
          vgcViewType: $vgcViewType,
          vgcViewStatus: $vgcViewStatus,
        ) {
          offsetInfo {
            total
            offset
          }
          views {
            id
            applicationId
            applicationName
            apparentPlatform
            publisher
            icon {
              url
              upgradedIconUrl
              sizes
            }
            ownerNaId
            userNaId
            isHidden
            isLending
            isPartialLending
            lendingExpireDatetime
            insertedNsDeviceId
            hasApplication
            hasAddOnContents
            hasUpgrade
            hasNxApplication
            hasNxAddOnContents
            hasOunceApplication
            hasOunceAddOnContents
            containsReleased
          }
        }
      }
    }
  }"""


class NintendoVgcAuthError(Exception):
    """Session expired or VGC portal not reachable while signed in."""


class NintendoVgcCaptureError(Exception):
    """Signed-in session present but VGC list could not be parsed."""


def parse_vgc_embedded_json(page_html: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract ``data`` and ``state`` JSON blobs embedded in the VGC portal HTML."""
    data_match = DATA_JSON_RE.search(page_html or "")
    state_match = STATE_JSON_RE.search(page_html or "")
    if not data_match:
        raise NintendoVgcCaptureError("VGC portal page missing embedded data-json.")
    try:
        data = json.loads(html.unescape(data_match.group(1)))
        state = json.loads(html.unescape(state_match.group(1))) if state_match else {}
    except (json.JSONDecodeError, TypeError) as exc:
        raise NintendoVgcCaptureError(f"VGC embedded JSON parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise NintendoVgcCaptureError("VGC data-json was not an object.")
    if not isinstance(state, dict):
        state = {}
    return data, state


def region_from_vgc_state(state: dict[str, Any]) -> dict[str, Any]:
    """Map portal state to Savanna GraphQL region variables."""
    user = state.get("user") if isinstance(state.get("user"), dict) else {}
    country = (
        state.get("country")
        or user.get("country")
        or user.get("countryCode")
        or ""
    )
    if isinstance(country, str) and country.upper() in REGION_DEFAULTS:
        return dict(REGION_DEFAULTS[country.upper()])
    lang = str(state.get("lang") or user.get("language") or "").lower()
    if lang.startswith("en-gb"):
        return dict(REGION_DEFAULTS["GB"])
    if lang.startswith("en-ca"):
        return dict(REGION_DEFAULTS["CA"])
    return dict(REGION_DEFAULTS["US"])


def _platform_label(view: dict[str, Any]) -> str | None:
    platform = (view.get("apparentPlatform") or "").upper()
    if platform == "NX" or view.get("hasNxApplication") or view.get("hasNxAddOnContents"):
        return "Nintendo Switch"
    if platform == "OUNCE" or view.get("hasOunceApplication") or view.get(
        "hasOunceAddOnContents"
    ):
        return "Nintendo Switch 2"
    if platform:
        return platform
    return None


def map_vgc_view(view: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single VGC view row for catalog merge / probe diff."""
    icon = view.get("icon") if isinstance(view.get("icon"), dict) else {}
    icon_sizes = icon.get("sizes")
    icon_url = resolve_nintendo_icon_url(
        icon.get("upgradedIconUrl") or icon.get("url"),
        icon_sizes,
        prefer_large=True,
    )
    icon_standard = resolve_nintendo_icon_url(
        icon.get("url"),
        icon_sizes,
        prefer_large=False,
    )
    name = " ".join(str(view.get("applicationName") or "").split()).strip()
    app_id = str(view.get("applicationId") or view.get("id") or "").strip()
    is_dlc = bool(
        view.get("hasAddOnContents")
        or view.get("hasNxAddOnContents")
        or view.get("hasOunceAddOnContents")
    ) and not view.get("hasApplication")
    return {
        "application_id": app_id,
        "vgc_id": str(view.get("id") or ""),
        "name": name,
        "platform": _platform_label(view),
        "apparent_platform": view.get("apparentPlatform"),
        "publisher": view.get("publisher"),
        "icon_url": icon_url,
        "icon_url_standard": icon_standard,
        "icon_sizes": icon_sizes,
        "is_dlc": is_dlc,
        "is_lending": bool(view.get("isLending")),
        "is_partial_lending": bool(view.get("isPartialLending")),
        "lending_expire_datetime": view.get("lendingExpireDatetime"),
        "has_application": bool(view.get("hasApplication")),
        "has_addon_contents": bool(view.get("hasAddOnContents")),
        "has_upgrade": bool(view.get("hasUpgrade")),
        "has_nx_application": bool(view.get("hasNxApplication")),
        "has_nx_addon_contents": bool(view.get("hasNxAddOnContents")),
        "has_ounce_application": bool(view.get("hasOunceApplication")),
        "has_ounce_addon_contents": bool(view.get("hasOunceAddOnContents")),
        "contains_released": view.get("containsReleased"),
    }


def _merge_vgc_payload(
    payload: dict[str, Any],
    collected: list[dict[str, Any]],
    seen_ids: set[str],
) -> int:
    views = (
        payload.get("data", {})
        .get("account", {})
        .get("vgc", {})
        .get("vgcViews", {})
        .get("views")
    )
    if not isinstance(views, list):
        return 0
    added = 0
    for item in views:
        if not isinstance(item, dict):
            continue
        key = str(item.get("applicationId") or item.get("id") or "")
        if key and key in seen_ids:
            continue
        if key:
            seen_ids.add(key)
        collected.append(map_vgc_view(item))
        added += 1
    return added


def _portal_html_has_vgc_data(page_html: str) -> bool:
    return bool(DATA_JSON_RE.search(page_html or ""))


def _portal_html_looks_unsigned(page_html: str) -> bool:
    body = (page_html or "").lower()
    return ("log in" in body or "sign in" in body) and not _portal_html_has_vgc_data(page_html)


def fetch_vgc_portal_html(context: Any, *, user_agent: str, page: Any | None = None) -> str:
    """Load VGC portal HTML via HTTP GET with profile cookies, not SPA domcontentloaded."""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://accounts.nintendo.com/",
    }
    resp = context.request.get(VGC_PORTAL_URL, headers=headers, timeout=60_000)
    html_body = resp.text() if resp.status == 200 else ""
    if _portal_html_has_vgc_data(html_body):
        return html_body
    if _portal_html_looks_unsigned(html_body):
        raise NintendoVgcAuthError(
            "Nintendo session expired - reconnect Nintendo in Connections."
        )

    active_page = page
    if active_page is None:
        active_page = context.pages[0] if context.pages else context.new_page()
    try:
        active_page.goto(VGC_PORTAL_URL, wait_until="commit", timeout=30_000)
    except Exception as exc:
        raise NintendoVgcAuthError(
            f"Could not open Nintendo VGC portal: {exc}"
        ) from exc
    time.sleep(3)
    html_body = active_page.content()
    if _portal_html_looks_unsigned(html_body):
        raise NintendoVgcAuthError(
            "Nintendo session expired - reconnect Nintendo in Connections."
        )
    return html_body


class NintendoVgcClient:
    def __init__(
        self,
        *,
        profile_path: Path,
        headless: bool = True,
        user_agent: str | None = None,
    ) -> None:
        self._profile_path = profile_path
        self._headless = headless
        self._user_agent = user_agent or DEFAULT_USER_AGENT

    def fetch_all_cards(self) -> list[dict[str, Any]]:
        if not self._profile_path.exists():
            raise NintendoVgcAuthError(
                "Nintendo browser profile missing. Connect Nintendo in Connections first."
            )
        return self._fetch_via_browser_profile(self._profile_path)

    def _fetch_via_browser_profile(self, profile_path: Path) -> list[dict[str, Any]]:
        from auth.cdp_browser import launch_persistent_profile

        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        context = launch_persistent_profile(profile_path, headless=self._headless)
        try:
            page = context.pages[0] if context.pages else None
            html_body = fetch_vgc_portal_html(
                context, user_agent=self._user_agent, page=page
            )
            data, state = parse_vgc_embedded_json(html_body)
            id_token = data.get("idToken")
            shop_url = data.get("shopGraphQLApiUrl")
            savanna_client_id = data.get("savannaClientId")
            if not id_token or not shop_url or not savanna_client_id:
                raise NintendoVgcCaptureError(
                    "VGC portal data-json missing idToken, shopGraphQLApiUrl, or "
                    "savannaClientId."
                )

            region = region_from_vgc_state(state)
            offset = 0
            total = None
            while total is None or offset < total:
                body = {
                    "query": VGC_GRAPHQL_QUERY,
                    "variables": {
                        "country": region["country"],
                        "language": region["language"],
                        "shopId": region["shop_id"],
                        "nasLanguage": region["nas_language"],
                        "idToken": id_token,
                        "limit": VGC_PAGE_LIMIT,
                        "offset": offset,
                        "order": "ASC",
                        "sortBy": "ACTIVATED_DATE",
                    },
                }
                resp = context.request.post(
                    shop_url,
                    json=body,
                    headers={
                        "x-nintendo-savanna-client-id": str(savanna_client_id),
                        "User-Agent": self._user_agent,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=60_000,
                )
                if resp.status != 200:
                    raise NintendoVgcCaptureError(
                        f"VGC GraphQL HTTP {resp.status}: {resp.text()[:400]}"
                    )
                try:
                    payload = json.loads(resp.text())
                except json.JSONDecodeError as exc:
                    raise NintendoVgcCaptureError(
                        f"VGC GraphQL response was not JSON: {exc}"
                    ) from exc
                if payload.get("errors"):
                    raise NintendoVgcCaptureError(
                        f"VGC GraphQL errors: {payload.get('errors')}"
                    )
                _merge_vgc_payload(payload, collected, seen_ids)
                offset_info = (
                    payload.get("data", {})
                    .get("account", {})
                    .get("vgc", {})
                    .get("vgcViews", {})
                    .get("offsetInfo", {})
                )
                if not isinstance(offset_info, dict):
                    break
                total = int(offset_info.get("total") or 0)
                offset += VGC_PAGE_LIMIT
                if offset >= total:
                    break
                time.sleep(0.3)

            if not collected:
                raise NintendoVgcCaptureError("VGC portal returned zero game cards.")
            return collected
        finally:
            threading.Thread(target=context.close, daemon=True).start()
