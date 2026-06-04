"""Capture the signed-in xbox.com wishlist API call for headless token replay.

xbox.com renders the wishlist server-side (``__PRELOADED_STATE__``) but the
front-door client also talks to the Emerald API
(``emerald.xboxservices.com/xboxcomfd/...``) using a short-lived ``Authorization``
bearer minted from the MSA session. During the headed connect flow we record
those requests so the fetcher can replay them headlessly, and we dump a
redacted diagnostic file used to build/maintain the replay client.

The bearer is short-lived, so the dump never stores it in plaintext — only the
scheme/length. The real token is handed back to the connect worker and stored
in the encrypted credential blob.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Hosts the xbox.com front-door uses for catalog / collection / wishlist data.
_API_HINTS = (
    "emerald.xboxservices.com",
    "xboxservices.com",
    "collections.mp.microsoft.com",
    "displaycatalog.mp.microsoft.com",
    "cllpwa.microsoft.com",
)
# Path/host fragments that suggest the response carries the wishlist list itself.
_BODY_HINTS = ("wishlist", "collection", "productactions", "lists")
_MAX_ENTRIES = 80
_MAX_BODY = 80_000


def capture_dump_path(*, profile_id: str | None = None) -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir(profile_id=profile_id) / "xbox_wishlist" / "connect_capture.json"


def _redact_auth(auth: str | None) -> dict[str, Any]:
    if not auth:
        return {"present": False}
    scheme, _, rest = auth.partition(" ")
    return {"present": True, "scheme": scheme or None, "value_len": len(rest.strip())}


class WishlistApiSniffer:
    """Records xbox.com front-door API traffic during a headed connect session."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.token: str | None = None
        self.market: str | None = None
        self.wishlist_url: str | None = None

    def on_response(self, resp: Any) -> None:
        try:
            url = getattr(resp, "url", "") or ""
            low = url.lower()
            if not any(h in low for h in _API_HINTS):
                return
            if len(self.entries) >= _MAX_ENTRIES:
                return
            req = getattr(resp, "request", None)
            headers = (getattr(req, "headers", None) or {}) if req is not None else {}
            auth = headers.get("authorization")
            post = (getattr(req, "post_data", "") or "") if req is not None else ""
            is_wishlisty = any(h in low for h in _BODY_HINTS)

            entry: dict[str, Any] = {
                "url": url,
                "method": "POST" if post else "GET",
                "status": getattr(resp, "status", 0),
                "authorization": _redact_auth(auth),
                "ms_cv_present": "ms-cv" in headers,
                "signature_present": "signature" in headers,
                "post_data": post[:_MAX_BODY],
                "is_wishlist_candidate": is_wishlisty,
            }
            if is_wishlisty:
                try:
                    entry["response_sample"] = resp.text()[:_MAX_BODY]
                except Exception as exc:  # noqa: BLE001
                    entry["response_error"] = str(exc)
                if auth and not self.token:
                    self.token = auth.strip()
                    self.wishlist_url = url
            self.entries.append(entry)
        except Exception:  # noqa: BLE001
            # Never let capture break the sign-in flow.
            pass

    def dump(self, *, profile_id: str | None = None) -> Path | None:
        try:
            path = capture_dump_path(profile_id=profile_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "captured_at": datetime.now(UTC).isoformat(),
                "token_captured": bool(self.token),
                "wishlist_url": self.wishlist_url,
                "entry_count": len(self.entries),
                "entries": self.entries,
            }
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return path
        except Exception:  # noqa: BLE001
            return None

    def creds(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.token:
            out["XBOX_WISHLIST_TOKEN"] = self.token
        if self.market:
            out["XBOX_WISHLIST_MARKET"] = self.market
        return out
