"""Nintendo eShop purchase history via ec.nintendo.com API.

There is no official public API for owned games. The transaction history page
calls:

  GET https://ec.nintendo.com/api/my/transactions?limit=N&offset=M

while logged in. Replay the Cookie header from DevTools on that request.

History is limited to ~2 years per Nintendo support.
"""

from __future__ import annotations

import requests

TRANSACTIONS_URL = "https://ec.nintendo.com/api/my/transactions"
PAGE_SIZE = 50


class NintendoAuthError(Exception):
    pass


class NintendoClient:
    def __init__(self, cookie_header: str, user_agent: str | None = None) -> None:
        cookie = (cookie_header or "").strip()
        if not cookie:
            raise NintendoAuthError(
                "Set NINTENDO_COOKIE in .env. Sign in at ec.nintendo.com/my/transactions/, "
                "DevTools → Network → filter 'transactions' → copy the Cookie header."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Cookie": cookie,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://ec.nintendo.com/my/transactions/",
                "Origin": "https://ec.nintendo.com",
                "User-Agent": user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            }
        )

    def fetch_all_transactions(self) -> list[dict]:
        """Paginate until all transactions are retrieved."""
        out: list[dict] = []
        offset = 0
        total: int | None = None

        while total is None or offset < total:
            try:
                resp = self.session.get(
                    TRANSACTIONS_URL,
                    params={"limit": PAGE_SIZE, "offset": offset},
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise NintendoAuthError(f"Request failed: {exc}") from exc

            if resp.status_code in (401, 403):
                raise NintendoAuthError(
                    f"Nintendo rejected the cookie ({resp.status_code}). "
                    "Refresh NINTENDO_COOKIE from ec.nintendo.com/my/transactions/."
                )
            if resp.status_code >= 400:
                body_snip = resp.text[:300]
                hint = ""
                if resp.status_code == 400 and (
                    "9001-1620" in body_snip or "sign in again" in body_snip.lower()
                ):
                    hint = (
                        " Session expired — open the Connections tab to reconnect Nintendo, "
                        "or refresh NINTENDO_COOKIE from ec.nintendo.com/my/transactions/ "
                        "(DevTools → Network → transactions request → Cookie header)."
                    )
                raise NintendoAuthError(f"Nintendo API {resp.status_code}: {body_snip}{hint}")

            try:
                body = resp.json()
            except ValueError as exc:
                raise NintendoAuthError(
                    "Non-JSON response — cookie likely expired or wrong page. "
                    "Re-copy Cookie from the transactions?limit= request."
                ) from exc

            if body.get("error"):
                err = body["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise NintendoAuthError(f"Nintendo API error: {msg}")

            batch = body.get("transactions")
            if batch is None:
                raise NintendoAuthError(
                    "Response missing 'transactions'. Re-copy Cookie from "
                    "ec.nintendo.com/api/my/transactions in DevTools."
                )

            if not isinstance(batch, list):
                raise NintendoAuthError("Unexpected transactions payload type.")

            total = int(body.get("total", len(batch)))
            out.extend(t for t in batch if isinstance(t, dict))

            if not batch:
                break
            offset += PAGE_SIZE

        return out
