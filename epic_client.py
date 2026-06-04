"""Epic Games Store client.

Auth flow:
1. User visits the login URL we print and logs in.
2. Epic redirects to a JSON page containing `authorizationCode`.
3. User pastes the code as EPIC_AUTH_CODE in .env (one-time, 5-min lifetime).
4. We exchange it for access + refresh tokens via OAuth.
5. Refresh token is cached to cache/epic/session.json (good ~30 days).
   On subsequent runs we use the refresh token automatically.

Library:
- /library/api/public/items returns paginated records with catalogItemId + namespace.
- /catalog/api/shared/bulk/items returns metadata for one or more catalog items.

The client credentials below are the well-known launcher pair used by community
tools like legendary; they grant access only when paired with a real user code.
"""

import base64
import json
import threading
import time
from pathlib import Path

import requests


def _legacy_epic_cache_dir() -> Path:
    from shared.profile_paths import ROOT

    return ROOT / "cache" / "epic"


def default_epic_cache_dir() -> Path:
    from shared.profile_paths import epic_cache_dir

    return epic_cache_dir()

OAUTH_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
LIBRARY_URL = "https://library-service.live.use1a.on.epicgames.com/library/api/public/items"
CATALOG_HOST = "catalog-public-service-prod06.ol.epicgames.com"
LOGIN_URL = (
    "https://www.epicgames.com/id/api/redirect"
    "?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code"
)

CLIENT_ID = "34a02cf8f4414e29b15921876da36f9a"
CLIENT_SECRET = "daafbccc737745039dffe53d94fc76cf"


def build_epic_oauth_login_url(redirect_uri: str, state: str = "") -> str:
    """Epic login URL that hands the authorizationCode back to ``redirect_uri``.

    ``LOGIN_URL`` omits a ``redirectUrl`` so Epic's ``id/api/redirect`` endpoint
    renders the code as JSON (scraped by the Playwright flow). Supplying a
    ``redirectUrl`` instead makes Epic redirect the browser to our local
    ``/oauth/epic/callback`` with ``?code=`` appended, so the GET callback can
    exchange it. ``state`` is round-tripped for CSRF + profile binding.
    """
    from urllib.parse import quote, urlencode

    target = redirect_uri
    if state:
        sep = "&" if "?" in target else "?"
        target = f"{target}{sep}{urlencode({'state': state})}"
    inner = (
        "https://www.epicgames.com/id/api/redirect"
        f"?clientId={CLIENT_ID}&responseType=code&redirectUrl={quote(target, safe='')}"
    )
    return f"https://www.epicgames.com/id/login?lang=en&redirectUrl={quote(inner, safe='')}"



BASIC_AUTH = "basic " + base64.b64encode(
    f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
).decode()

REQUEST_DELAY_SEC = 0.12


class EpicAuthError(Exception):
    """Authorization code missing/expired or refresh token rejected."""


class EpicClient:
    def __init__(self, auth_code: str | None = None, *, cache_dir: Path | None = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "steam-backlog/1.0"})
        self._cache_dir = cache_dir or default_epic_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self._cache_dir / "session.json"
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._account_id: str | None = None
        self._last_request = 0.0
        self._auth_code = auth_code
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_request
            if elapsed < REQUEST_DELAY_SEC:
                time.sleep(REQUEST_DELAY_SEC - elapsed)
            self._last_request = time.time()

    def _save_session(self) -> None:
        self._session_file.write_text(
            json.dumps(
                {"refresh_token": self._refresh_token, "account_id": self._account_id},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _migrate_legacy_session(self) -> None:
        legacy = _legacy_epic_cache_dir() / "session.json"
        if legacy.is_file() and not self._session_file.is_file():
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._session_file.write_bytes(legacy.read_bytes())

    def _load_session(self) -> dict | None:
        self._migrate_legacy_session()
        if not self._session_file.exists():
            return None
        try:
            return json.loads(self._session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _request_token(self, params: dict) -> dict:
        self._throttle()
        resp = self.session.post(
            OAUTH_URL,
            data=params,
            headers={
                "Authorization": BASIC_AUTH,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "steam-backlog/1.0",
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json().get("errorCode", resp.text[:200])
            except json.JSONDecodeError:
                err = resp.text[:200]
            raise EpicAuthError(f"OAuth {resp.status_code}: {err}")
        return resp.json()

    def login(self) -> None:
        """Authenticate using cached refresh token, falling back to auth code."""
        cached = self._load_session()
        if cached and cached.get("refresh_token"):
            try:
                data = self._request_token(
                    {"grant_type": "refresh_token", "refresh_token": cached["refresh_token"]}
                )
                self._apply_tokens(data)
                return
            except EpicAuthError as e:
                print(f"  refresh token rejected ({e}); falling back to auth code")

        if not self._auth_code:
            raise EpicAuthError(
                "No valid Epic session. Run: python fetch_epic.py --auth-help"
            )

        data = self._request_token(
            {"grant_type": "authorization_code", "code": self._auth_code, "token_type": "eg1"}
        )
        self._apply_tokens(data)

    def _apply_tokens(self, data: dict) -> None:
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        self._account_id = data.get("account_id")
        if not self._access_token:
            raise EpicAuthError("OAuth response missing access_token")
        self._save_session()

    def _auth_headers(self) -> dict:
        return {"Authorization": f"bearer {self._access_token}"}

    def get_library_records(self) -> list[dict]:
        """All entitlement records (paginated) for the logged-in user."""
        records: list[dict] = []
        cursor: str | None = None
        while True:
            self._throttle()
            params: dict = {"includeMetadata": "true"}
            if cursor:
                params["cursor"] = cursor
            resp = self.session.get(
                LIBRARY_URL, params=params, headers=self._auth_headers(), timeout=30
            )
            if resp.status_code == 401:
                raise EpicAuthError("Library 401: access token expired")
            resp.raise_for_status()
            data = resp.json()
            records.extend(data.get("records", []))
            cursor = data.get("responseMetadata", {}).get("nextCursor")
            if not cursor:
                break
        return records

    def get_catalog_item(
        self, namespace: str, catalog_id: str, country: str = "US", locale: str = "en-US"
    ) -> dict | None:
        """Catalog metadata for one item (legendary-compatible endpoint)."""
        self._throttle()
        resp = self.session.get(
            f"https://{CATALOG_HOST}/catalog/api/shared/namespace/{namespace}/bulk/items",
            params={
                "id": catalog_id,
                "includeDLCDetails": "true",
                "includeMainGameDetails": "true",
                "country": country,
                "locale": locale,
            },
            headers=self._auth_headers(),
            timeout=30,
        )
        if resp.status_code == 401:
            raise EpicAuthError("Catalog 401: access token expired")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get(catalog_id)

    def get_catalog_bulk(
        self, namespace: str, catalog_ids: list[str], country: str = "US",
        locale: str = "en-US",
    ) -> dict:
        """Bulk metadata for catalog items in a single namespace."""
        out: dict = {}
        for cid in catalog_ids:
            item = self.get_catalog_item(namespace, cid, country=country, locale=locale)
            if item:
                out[cid] = item
        return out

    @property
    def account_id(self) -> str | None:
        return self._account_id


# Launcher OAuth can't reach the storefront wishlist (auth context differs).
# EpicStoreClient (below) uses the same cookies your browser sends to
# www.epicgames.com — paste the request Cookie header from DevTools as
# EPIC_STORE_COOKIE in .env.
STORE_GRAPHQL_URL = "https://store.epicgames.com/graphql"


class EpicStoreClient:
    """Storefront GraphQL client authenticated via the browser session cookie.

    Use this for endpoints that live behind ``www.epicgames.com`` (wishlist,
    receipts, etc.) — i.e. anything the launcher OAuth bearer can't reach.
    """

    def __init__(self, cookie: str):
        self.session = requests.Session()
        cookie = (cookie or "").strip()
        if cookie.lower().startswith("cookie:"):
            cookie = cookie.split(":", 1)[1].strip()
        if not cookie:
            raise EpicAuthError(
                "EPIC_STORE_COOKIE is empty. See README for instructions."
            )
        self._cookie = cookie
        self._last_request = 0.0
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_request
            if elapsed < REQUEST_DELAY_SEC:
                time.sleep(REQUEST_DELAY_SEC - elapsed)
            self._last_request = time.time()

    def _headers(self) -> dict:
        return {
            "Cookie": self._cookie,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://store.epicgames.com",
            "Referer": "https://store.epicgames.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        }

    def graphql(self, query: str, variables: dict, operation_name: str) -> dict:
        self._throttle()
        resp = self.session.post(
            STORE_GRAPHQL_URL,
            json={
                "query": query,
                "operationName": operation_name,
                "variables": variables,
            },
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code in (401, 403):
            raise EpicAuthError(
                f"Storefront GraphQL {resp.status_code}: cookie expired or wrong "
                "(grab a fresh EPIC_STORE_COOKIE from DevTools — see README)."
            )
        if resp.status_code >= 400:
            body = resp.text[:1500] if resp.text else "<empty>"
            raise EpicAuthError(
                f"Storefront GraphQL {resp.status_code}: {body}"
            )
        payload = resp.json()
        errors = payload.get("errors") or []
        if errors:
            raise EpicAuthError(f"GraphQL errors: {errors[0].get('message')}")
        return payload.get("data") or {}

    def get_wishlist(
        self, country: str = "US", locale: str = "en-US",
    ) -> list[dict]:
        """All wishlist items for the cookie's logged-in user.

        Each element has ``offerId``, ``namespace``, ``created``, and an
        embedded ``offer`` with title/keyImages/price/productSlug/releaseDate.
        """
        all_elements: list[dict] = []
        seen_ids: set[str] = set()
        for start in (0, 200, 400, 600, 800):
            data = self.graphql(
                _WISHLIST_QUERY,
                {"country": country, "locale": locale, "start": start, "count": 200},
                "getWishlistQuery",
            )
            elements = (
                ((data.get("Wishlist") or {}).get("wishlistItems") or {})
                .get("elements", [])
            )
            if not elements:
                break
            added_this_page = 0
            for el in elements:
                if not isinstance(el, dict):
                    continue
                eid = el.get("id")
                if eid in seen_ids:
                    continue
                if eid is not None:
                    seen_ids.add(eid)
                all_elements.append(el)
                added_this_page += 1
            if len(elements) < 200 or added_this_page == 0:
                break
        return all_elements


def validate_store_wishlist_cookie(cookie: str) -> bool:
    """True when the storefront cookie can read the wishlist GraphQL API."""
    try:
        client = EpicStoreClient(cookie)
        client.graphql(
            _WISHLIST_QUERY,
            {"country": "US", "locale": "en-US", "start": 0, "count": 1},
            "getWishlistQuery",
        )
        return True
    except EpicAuthError:
        return False
    except Exception:  # noqa: BLE001
        return False


_WISHLIST_QUERY = """
query getWishlistQuery($country: String!, $locale: String, $start: Int, $count: Int) {
  Wishlist {
    wishlistItems(start: $start, count: $count) {
      elements {
        id
        order
        created
        offerId
        updated
        namespace
        offer(locale: $locale) {
          productSlug
          urlSlug
          title
          id
          namespace
          offerType
          effectiveDate
          pcReleaseDate
          releaseDate
          keyImages { type url }
          seller { name }
          categories { path }
          tags { id name }
          developerDisplayName
          publisherDisplayName
          price(country: $country) {
            totalPrice {
              discountPrice
              originalPrice
              discount
              currencyCode
              fmtPrice(locale: $locale) {
                originalPrice
                discountPrice
              }
            }
          }
        }
      }
    }
  }
}
"""
