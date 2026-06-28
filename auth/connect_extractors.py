import queue
import threading

HUMBLE_LIBRARY_URL = "https://www.humblebundle.com/home/library"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
BATTLENET_GAMES_URL = "https://account.battle.net/games"


def pick_gog_al_from_cookies(cookies):
    gog_al = next((c["value"] for c in cookies if c.get("name") == "gog-al" and c.get("value")), "")
    if gog_al:
        return str(gog_al)
    parts = []
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if "gog.com" not in domain:
            continue
        name = c.get("name") or ""
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    header = "; ".join(parts)
    if "gog-al=" in header:
        return header.split("gog-al=")[-1].split(";")[0].strip()
    return ""


def _cookie_header(cookies, domains):
    parts = []
    for c in cookies:
        domain = (c.get("domain") or "").lstrip(".")
        if not any((domain.endswith(d.lstrip(".")) or d.lstrip(".") in domain for d in domains)):
            continue
        name = c.get("name") or ""
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _humble_has_session(context):
    try:
        resp = context.request.get(HUMBLE_ORDERS_API, timeout=15000)
        if resp.status == 200:
            body = resp.text().strip()
            if body.startswith("[") or body.startswith("{"):
                return True
        if resp.status in (401, 403):
            return False
    except Exception:
        pass
    return False


def _battlenet_has_session(context):
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if domain.endswith("battle.net") and c.get("name") and c.get("value"):
            return True
    return False


class HeaderSniffer:
    def __init__(self, *, url_substr, fields, normalize=None):
        self.url_substr = url_substr.lower()
        self.fields = {k.lower(): v for k, v in fields.items()}
        self.normalize = normalize
        self.captured = {}

    def attach(self, context):

        def on_request(request):
            url = (getattr(request, "url", None) or "").lower()
            if self.url_substr not in url:
                return
            headers = getattr(request, "headers", {}) or {}
            for header_key, cred_key in self.fields.items():
                val = headers.get(header_key) or headers.get(header_key.title())
                if not val:
                    continue
                if self.normalize and cred_key.endswith("TOKEN"):
                    norm = self.normalize(val)
                    if norm:
                        self.captured[cred_key] = norm
                else:
                    self.captured[cred_key] = str(val).strip()

        context.on("request", on_request)

    def ready(self):
        return all((self.captured.get(k) for k in self.fields.values()))

    def creds(self):
        return dict(self.captured)


class GraphqlResponseSniffer:
    def __init__(self, *, url_match, accept):
        self.url_match = url_match
        self.accept = accept
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self.matched = False

    def attach(self, page):

        def on_response(response):
            try:
                url = getattr(response, "url", None) or ""
                if not self.url_match(url):
                    return
                if int(getattr(response, "status", 0) or 0) != 200:
                    return
                payload = response.json()
                if not isinstance(payload, dict):
                    return
                self._queue.put(payload)
            except Exception:
                pass

        page.on("response", on_response)

    def drain(self):
        changed = False
        while True:
            try:
                payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if self.accept(payload):
                with self._lock:
                    self.matched = True
                changed = True
        return changed

    @property
    def success(self):
        with self._lock:
            return self.matched


def extract_gog_session(context):
    gog_al = pick_gog_al_from_cookies(context.cookies())
    if gog_al:
        return {"GOG_AL": gog_al}
    return None


def gog_connect_hint(page):
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "auth" in url:
        return "Sign in to your GOG account in the browser window."
    return "Sign in at gog.com if prompted. We'll save your session automatically once you're logged in."


def extract_humble_session(context, page):
    if _humble_has_session(context):
        try:
            page.goto(HUMBLE_LIBRARY_URL, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)
        except Exception:
            pass
        return {"HUMBLE_PROFILE": "ready"}
    return None


def humble_connect_hint(page):
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or ("sign" in url and "library" not in url):
        return "Sign in to Humble Bundle in the browser window (email or Google)."
    if "humblebundle.com" not in url:
        return "Open humblebundle.com and sign in if prompted."
    return "On humblebundle.com? We'll open your library to confirm the session."


def extract_battlenet_session(context):
    from clients.battlenet_client import probe_session

    if not _battlenet_has_session(context):
        return None
    header = _cookie_header(context.cookies(), (".battle.net", "battle.net"))
    if not header:
        return None
    probe_session(header)
    return {"BATTLENET_COOKIE": header}


def battlenet_connect_hint(page):
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "authorize" in url:
        return "Sign in to your Battle.net account in the browser window."
    if "battle.net" not in url:
        return "Open account.battle.net/games after signing in."
    return (
        "On your Games page? Wait until your library list finishes loading, then we'll save the session automatically."
    )


def extract_ea_bearer_session(context, *, sniffer):
    from clients.ea_session import probe_ea_token

    if not sniffer.captured.get("EA_BEARER_TOKEN"):
        return None
    token = sniffer.captured["EA_BEARER_TOKEN"]
    cookies = context.cookies()
    probe = probe_ea_token(token, cookies)
    if probe.get("ok"):
        return {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": token}
    err = (probe.get("error") or "")[:200]
    if "PersistedQueryNotFound" in err:
        return {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": token}
    sniffer.captured.clear()
    return None


def ea_connect_hint(page, *, saw_token):
    url = (getattr(page, "url", None) or "").lower()
    if "signin.ea.com" in url or "/login" in url:
        return "Sign in to your EA account in the browser window."
    if saw_token:
        return "Verifying your EA session — keep the window open."
    return "Signed in — wait for the deals page to finish loading so we can save your session."


def build_ea_header_sniffer():
    from clients.ea_session import EA_GRAPHQL_HOST, normalize_bearer

    return HeaderSniffer(
        url_substr=EA_GRAPHQL_HOST, fields={"authorization": "EA_BEARER_TOKEN"}, normalize=normalize_bearer
    )


class DeferredGraphqlResponseSniffer:
    def __init__(self, *, url_match, accept, debug_entry=None):
        self.url_match = url_match
        self.accept = accept
        self.debug_entry = debug_entry
        self._pending = []
        self._lock = threading.Lock()
        self.matched = False
        self.debug_log = []

    def attach(self, page):

        def on_response(response):
            try:
                url = getattr(response, "url", None) or ""
                if not self.url_match(url):
                    return
                if int(getattr(response, "status", 0) or 0) != 200:
                    return
                self._pending.append(response)
            except Exception:
                pass

        page.on("response", on_response)

    def drain(self):
        changed = False
        while self._pending:
            resp = self._pending.pop(0)
            try:
                payload = resp.json()
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if self.debug_entry is not None:
                try:
                    self.debug_log.append(self.debug_entry(getattr(resp, "url", "") or "", payload))
                except Exception:
                    pass
            if self.accept(payload):
                with self._lock:
                    self.matched = True
                changed = True
        return changed

    @property
    def success(self):
        with self._lock:
            return self.matched


def build_epic_wishlist_graphql_sniffer():
    from auth.epic_wishlist_session import graphql_debug_entry, is_epic_graphql_url, wishlist_graphql_ok

    return DeferredGraphqlResponseSniffer(
        url_match=is_epic_graphql_url, accept=wishlist_graphql_ok, debug_entry=graphql_debug_entry
    )


UBISOFT_API_HOST = "public-ubiservices.ubi.com"


def build_ubisoft_header_sniffer():
    return HeaderSniffer(
        url_substr=UBISOFT_API_HOST,
        fields={"authorization": "UBISOFT_AUTH", "ubi-sessionid": "UBISOFT_SESSION_ID", "ubi-appid": "UBISOFT_APP_ID"},
    )


def extract_ubisoft_session(sniffer):
    if sniffer.captured.get("UBISOFT_AUTH") and sniffer.captured.get("UBISOFT_SESSION_ID"):
        return sniffer.creds()
    return None


def ubisoft_session_captured(sniffer):
    return bool(sniffer.captured.get("UBISOFT_AUTH") and sniffer.captured.get("UBISOFT_SESSION_ID"))


def ubisoft_connect_hint(*, urls, seen_success, captured):
    joined = " ".join(urls)
    if "account.ubisoft" in joined or "login" in joined:
        return "Finish Ubisoft sign-in and 2FA in the browser window (use the popup if it stays open). Close DevTools if you see a yellow 'Debugger paused' banner."
    if seen_success and (not captured):
        return "Signed in — opening your Ubisoft games list to finish capturing the session."
    if not captured:
        return "Signed in? Open your Ubisoft Connect games list so we can capture the session."
    return "Almost there — keep the window open while we finish capturing your session."


NINTENDO_ACCOUNT_URL = "https://ec.nintendo.com/my/transactions/"
_NINTENDO_SESSION_COOKIES = ("MIST", "JViDD", "_gh_sess", "NASID", "ecsid", "__Secure-next-auth.session-token")


def nintendo_has_session(context):
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if not domain.startswith("ec.nintendo.com"):
            continue
        name = c.get("name") or ""
        if name in _NINTENDO_SESSION_COOKIES and c.get("value"):
            return True
    return False


def nintendo_session_has_id_token(context):
    try:
        from clients.nintendo_client import PLAYWRIGHT_REQUEST_TIMEOUT_MS, probe_session_id_token

        return bool(probe_session_id_token(context.request.get, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS).get("ok"))
    except Exception:
        return False


def extract_nintendo_session(context):
    if not nintendo_has_session(context) or not nintendo_session_has_id_token(context):
        return None
    header = _cookie_header(context.cookies(), ("nintendo.com",))
    if header:
        return {"NINTENDO_COOKIE": header}
    return None


def nintendo_connect_hint(page, *, on_account):
    url = (getattr(page, "url", None) or "").lower()
    if "login" in url or "signin" in url or "authorize" in url:
        return "Sign in to your Nintendo Account in the browser window."
    if on_account:
        return "Signed in — opening your eShop transactions page to capture the session."
    return "Loading your Nintendo eShop transactions — keep the window open."


def cookie_header(cookies, domains):
    return _cookie_header(cookies, domains)
