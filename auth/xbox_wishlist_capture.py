import json
from datetime import UTC, datetime

_API_HINTS = (
    "emerald.xboxservices.com",
    "xboxservices.com",
    "collections.mp.microsoft.com",
    "displaycatalog.mp.microsoft.com",
    "cllpwa.microsoft.com",
)
_BODY_HINTS = ("wishlist", "collection", "productactions", "lists")
_MAX_ENTRIES = 80
_MAX_BODY = 80000


def capture_dump_path(*, profile_id=None):
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir(profile_id=profile_id) / "xbox_wishlist" / "connect_capture.json"


def _redact_auth(auth):
    if not auth:
        return {"present": False}
    scheme, _, rest = auth.partition(" ")
    return {"present": True, "scheme": scheme or None, "value_len": len(rest.strip())}


class WishlistApiSniffer:
    def __init__(self):
        self.entries = []
        self.token = None
        self.market = None
        self.wishlist_url = None

    def on_response(self, resp):
        try:
            url = getattr(resp, "url", "") or ""
            low = url.lower()
            if not any((h in low for h in _API_HINTS)):
                return
            if len(self.entries) >= _MAX_ENTRIES:
                return
            req = getattr(resp, "request", None)
            headers = getattr(req, "headers", None) or {} if req is not None else {}
            auth = headers.get("authorization")
            post = getattr(req, "post_data", "") or "" if req is not None else ""
            is_wishlisty = any((h in low for h in _BODY_HINTS))
            entry = {
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
                except Exception as exc:
                    entry["response_error"] = str(exc)
                if auth and (not self.token):
                    self.token = auth.strip()
                    self.wishlist_url = url
            self.entries.append(entry)
        except Exception:
            pass

    def dump(self, *, profile_id=None):
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
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return path
        except Exception:
            return None

    def creds(self):
        out = {}
        if self.token:
            out["XBOX_WISHLIST_TOKEN"] = self.token
        if self.market:
            out["XBOX_WISHLIST_MARKET"] = self.market
        return out
