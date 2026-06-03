"""Nintendo eShop purchase history via ec.nintendo.com (Savanna GraphQL).

The legacy REST endpoint ``/api/my/transactions`` was removed when Nintendo
redesigned the transactions site. Purchase history is now loaded from:

  GET https://wb.lp1.savanna.srv.nintendo.net/graphql
      ?operationName=TransactionsClientRootClient
      (persisted query + idToken from /api/auth/session)

Those GraphQL calls only succeed from a logged-in browser context (correct
headers / token binding). We reuse the Connections CDP profile
(``cache/auth/profiles/nintendo``) headlessly: open the transactions page,
capture GraphQL responses, and paginate via the on-page controls.

History is limited to ~2 years per Nintendo support.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

GRAPHQL_URL = "https://wb.lp1.savanna.srv.nintendo.net/graphql"
SESSION_URL = "https://ec.nintendo.com/api/auth/session"
TRANSACTIONS_PAGE = "https://ec.nintendo.com/my/transactions/1"
PERSISTED_QUERY_HASH = (
    "5cd77203b74514954049c93f6e3a5ed66d5647eb2714bd6bf72ebd470a25a08e"
)
PAGE_SIZE = 10
LEGACY_TRANSACTIONS_URL = "https://ec.nintendo.com/api/my/transactions"


class NintendoAuthError(Exception):
    """Cookie/session expired or missing — reconnect Nintendo in Connections."""


class NintendoEndpointError(Exception):
    """Unexpected API shape (should not occur with the browser path)."""


def _looks_like_html(resp: requests.Response) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype:
        return True
    head = (resp.text or "")[:200].lstrip().lower()
    return head.startswith("<!doctype") or head.startswith("<html")


class NintendoClient:
    def __init__(
        self,
        cookie_header: str = "",
        *,
        profile_path: Path | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._cookie = (cookie_header or "").strip()
        self._profile_path = profile_path
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

    def fetch_all_transactions(self) -> list[dict]:
        """Return raw transaction dicts compatible with fetch_nintendo merge logic."""
        if self._profile_path and self._profile_path.exists():
            return self._fetch_via_browser_profile(self._profile_path)
        if self._cookie:
            return self._fetch_via_cookie_requests()
        raise NintendoAuthError(
            "Nintendo is not connected. Open Connections, connect Nintendo, "
            "and complete sign-in on ec.nintendo.com (transactions page)."
        )

    def _fetch_via_cookie_requests(self) -> list[dict]:
        """Legacy path: cookie jar only (often incomplete after the site redesign)."""
        session = requests.Session()
        session.headers.update(
            {
                "Cookie": self._cookie,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://ec.nintendo.com/my/transactions/",
                "Origin": "https://ec.nintendo.com",
                "User-Agent": self._user_agent,
            }
        )
        auth = session.get(SESSION_URL, timeout=30)
        if auth.status_code in (401, 403):
            raise NintendoAuthError(
                f"Nintendo rejected the session ({auth.status_code}). "
                "Reconnect Nintendo in Connections."
            )
        if not auth.ok:
            raise NintendoAuthError(
                f"Could not load Nintendo session ({auth.status_code}). "
                "Reconnect Nintendo in Connections."
            )
        try:
            body = auth.json()
        except ValueError as exc:
            raise NintendoAuthError(
                "Nintendo session response was not JSON — reconnect in Connections."
            ) from exc
        if not body.get("idToken"):
            raise NintendoAuthError(
                "Nintendo cookie is incomplete (no idToken). Reconnect Nintendo in "
                "Connections so the full eShop session is saved to the browser profile."
            )
        raise NintendoAuthError(
            "Nintendo now requires the saved browser profile for purchase history. "
            "Reconnect Nintendo in Connections, then run the fetcher again."
        )

    def _fetch_via_browser_profile(self, profile_path: Path) -> list[dict]:
        from auth.cdp_browser import launch_persistent_profile

        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def on_response(resp) -> None:
            url = getattr(resp, "url", "") or ""
            if "graphql" not in url or "TransactionsClientRootClient" not in url:
                return
            if getattr(resp, "status", 0) != 200:
                return
            try:
                payload = json.loads(resp.text())
            except (ValueError, TypeError):
                return
            histories = (
                payload.get("data", {})
                .get("account", {})
                .get("transactionHistories", {})
            )
            batch = histories.get("transactionHistories")
            if not isinstance(batch, list):
                return
            for item in batch:
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("transactionId") or "")
                if tid and tid in seen_ids:
                    continue
                if tid:
                    seen_ids.add(tid)
                collected.append(item)

        with launch_persistent_profile(profile_path, headless=True) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", on_response)
            try:
                page.goto(
                    TRANSACTIONS_PAGE,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            except Exception as exc:
                raise NintendoAuthError(
                    f"Could not open Nintendo transactions page: {exc}"
                ) from exc
            time.sleep(12)
            self._paginate_transactions_ui(page)
            time.sleep(3)

            if not collected:
                html = ""
                try:
                    html = page.content().lower()
                except Exception:
                    pass
                if "log in" in html or "sign up" in html:
                    raise NintendoAuthError(
                        "Nintendo session expired — open Connections and reconnect Nintendo."
                    )
                raise NintendoAuthError(
                    "No purchase history returned. Sign in at ec.nintendo.com/my/transactions/ "
                    "in Connections, then retry."
                )
        return [_map_graphql_item(item) for item in collected]

    def _paginate_transactions_ui(self, page) -> None:
        """Click numeric pagination buttons to load additional GraphQL pages."""
        try:
            labels = page.evaluate(
                """() => [...document.querySelectorAll('button, a')]
                    .map(el => (el.innerText || '').trim())
                    .filter(t => /^\\d+$/.test(t))
                    .map(t => parseInt(t, 10))
                    .filter(n => n > 1)"""
            )
        except Exception:
            return
        if not isinstance(labels, list):
            return
        for page_num in sorted(set(int(x) for x in labels if isinstance(x, (int, float)))):
            try:
                page.evaluate(
                    f"""() => {{
                        const want = {page_num};
                        const el = [...document.querySelectorAll('button, a')]
                            .find(n => (n.innerText || '').trim() === String(want));
                        if (el) el.click();
                    }}"""
                )
            except Exception:
                continue
            time.sleep(2.5)


def _map_graphql_item(item: dict[str, Any]) -> dict[str, Any]:
    """Map Savanna GraphQL row to the legacy REST-shaped dict fetch_nintendo expects."""
    title = (item.get("title") or "").strip()
    dt = (item.get("datetime") or "").strip()
    date = dt[:10] if len(dt) >= 10 else dt
    tid = item.get("transactionId")
    platform = item.get("labelPlatform")
    device_type = "Nintendo Switch" if platform == "HAC" else platform
    item_type = (item.get("itemType") or "").lower()
    tx_type = (item.get("transactionType") or "").lower()
    return {
        "title": title,
        "date": date,
        "transaction_id": str(tid) if tid is not None else "",
        "device_type": device_type,
        "content_type": item_type,
        "transaction_type": tx_type,
    }

