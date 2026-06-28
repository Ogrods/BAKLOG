import requests

BASE = "https://xbl.io/api/v2"


class XboxAuthError(Exception):
    pass


class XboxRateLimitError(XboxAuthError):
    pass


def _rate_limit_message(resp):
    msg = "OpenXBL rate limit reached (HTTP 429). The free OpenXBL tier caps requests per hour — your API key is still valid, just wait and retry."
    retry_after = (resp.headers.get("Retry-After") or "").strip()
    if retry_after:
        msg += f" Retry after {retry_after}s."
    return msg


class XboxClient:
    def __init__(self, api_key):
        key = (api_key or "").strip()
        if not key:
            raise XboxAuthError("Set XBL_API_KEY in .env (free key from https://xbl.io/)")
        self.session = requests.Session()
        self.session.headers.update(
            {"X-Authorization": key, "Accept": "application/json", "User-Agent": "steam-backlog/1.0"}
        )

    def _get(self, path, timeout=60):
        url = f"{BASE}/{path.lstrip('/')}"
        resp = self.session.get(url, timeout=timeout)
        if resp.status_code == 401:
            raise XboxAuthError("Invalid XBL_API_KEY")
        if resp.status_code == 429:
            raise XboxRateLimitError(_rate_limit_message(resp))
        if resp.status_code >= 400:
            raise XboxAuthError(f"OpenXBL {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if isinstance(data, dict) and data.get("code") not in (None, 200, "200", "SUCCESS"):
            code = data.get("code")
            msg = data.get("message") or code
            if str(code).strip() == "429" or str(msg).strip() == "429":
                raise XboxRateLimitError(_rate_limit_message(resp))
            raise XboxAuthError(f"OpenXBL error: {msg}")
        return data

    def get_account(self):
        return self._get("account")

    def get_xuid(self):
        data = self.get_account()
        content = data.get("content") or data
        users = content.get("profileUsers") or []
        if not users:
            raise XboxAuthError("No profile on OpenXBL account response")
        return str(users[0].get("id") or users[0].get("hostId") or "")

    def get_gamertag(self):
        data = self.get_account()
        content = data.get("content") or data
        users = content.get("profileUsers") or []
        if not users:
            return None
        settings = {s.get("id"): s.get("value") for s in users[0].get("settings") or []}
        return settings.get("Gamertag")

    def get_title_history(self):
        data = self._get("player/titleHistory")
        content = data.get("content") or data
        titles = content.get("titles") or []
        return [t for t in titles if isinstance(t, dict)]
