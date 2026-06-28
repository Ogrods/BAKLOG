import requests

BASE_URL = "https://public-ubiservices.ubi.com"
DEFAULT_APP_ID = "f35adcb5-1911-440c-b1c9-48fdc1701c68"
APPLICATIONS_PATH = "/v2/profiles/me/applications"
GAMESPLAYED_PATH = "/v1/profiles/me/gamesplayed"
CATALOG_PATH = "/v1/spaces/global/ubiconnect/games/api/catalog"
CATALOG_BATCH_SIZE = 12


class UbisoftAuthError(Exception):
    pass


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class UbisoftClient:
    def __init__(self, auth, session_id, app_id=None, user_agent=None):
        auth = (auth or "").strip()
        session_id = (session_id or "").strip()
        if not auth or not session_id:
            raise UbisoftAuthError(
                "Set UBISOFT_AUTH and UBISOFT_SESSION_ID in .env. From DevTools → Network on ubisoft.com, copy Authorization (Ubi_v1 t=...) and Ubi-SessionId."
            )
        if auth.lower().startswith("ubi_v1"):
            rest = auth.split(" ", 1)
            ticket = rest[1] if len(rest) > 1 else auth[6:].lstrip("t=").lstrip("=")
            if ticket.lower().startswith("t="):
                ticket = ticket[2:]
            auth = f"Ubi_v1 t={ticket}"
        elif not auth.lower().startswith("ubi_v1"):
            auth = f"Ubi_v1 t={auth}"
        self.app_id = (app_id or DEFAULT_APP_ID).strip()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": auth,
                "Ubi-AppId": self.app_id,
                "Ubi-SessionId": session_id,
                "Ubi-Localecode": "en-US",
                "Ubi-Country": "US",
                "Ubi-RequestedPlatformType": "uplay",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Origin": "https://www.ubisoft.com",
                "Referer": "https://www.ubisoft.com/",
            }
        )

    def _get(self, path):
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        try:
            resp = self.session.get(url, timeout=30)
        except requests.RequestException as exc:
            return (0, None, str(exc))
        if resp.status_code in (401, 403):
            raise UbisoftAuthError(
                f"Ubisoft rejected the credentials ({resp.status_code}). Sign in again at ubisoft.com, then refresh UBISOFT_AUTH and UBISOFT_SESSION_ID from DevTools."
            )
        try:
            body = resp.json()
        except ValueError:
            body = None
        return (resp.status_code, body, resp.text[:200])

    def _fetch_catalog(self, space_ids):
        catalog = []
        seen_spaces = set()
        for chunk in _chunks(space_ids, CATALOG_BATCH_SIZE):
            qs = "&".join((f"spaceIds={sid}" for sid in chunk))
            status, body, text = self._get(f"{CATALOG_PATH}?{qs}")
            if status >= 400 or not isinstance(body, dict):
                print(f"  HTTP {status} for Ubisoft catalog batch ({len(chunk)} spaceIds): {text[:120]}", flush=True)
                continue
            for game in body.get("games") or []:
                if not isinstance(game, dict):
                    continue
                sid = game.get("spaceId")
                if sid and sid not in seen_spaces:
                    seen_spaces.add(sid)
                    catalog.append(game)
        return catalog

    def get_library(self):
        status, apps_body, _ = self._get(APPLICATIONS_PATH)
        if status >= 400 or not isinstance(apps_body, dict):
            raise UbisoftAuthError(
                f"Could not load applications ({status}). Refresh UBISOFT_AUTH / UBISOFT_SESSION_ID from DevTools."
            )
        status, played_body, _ = self._get(GAMESPLAYED_PATH)
        if status >= 400 or not isinstance(played_body, dict):
            raise UbisoftAuthError(f"Could not load games played ({status}). Refresh credentials.")
        games_played = [g for g in played_body.get("gamesPlayed") or [] if isinstance(g, dict)]
        applications = [a for a in apps_body.get("applications") or [] if isinstance(a, dict)]
        space_ids = list(dict.fromkeys((g["spaceId"] for g in games_played if isinstance(g.get("spaceId"), str))))
        catalog = self._fetch_catalog(space_ids) if space_ids else []
        endpoint = f"{APPLICATIONS_PATH}+{GAMESPLAYED_PATH}+{CATALOG_PATH}"
        return ({"applications": applications, "gamesPlayed": games_played, "catalog": catalog}, endpoint)
