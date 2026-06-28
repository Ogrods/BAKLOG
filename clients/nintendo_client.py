import json
import time
from urllib.parse import urlencode

import requests

GRAPHQL_URL = "https://wb.lp1.savanna.srv.nintendo.net/graphql"
SESSION_URL = "https://ec.nintendo.com/api/auth/session"
TRANSACTIONS_PAGE = "https://ec.nintendo.com/my/transactions/"
PERSISTED_QUERY_HASH = "5cd77203b74514954049c93f6e3a5ed66d5647eb2714bd6bf72ebd470a25a08e"
PAGE_SIZE = 10
LEGACY_TRANSACTIONS_URL = "https://ec.nintendo.com/api/my/transactions"
NINTENDO_SESSION_COOKIE_NAMES = frozenset(
    {"MIST", "JViDD", "_gh_sess", "NASID", "ecsid", "__Secure-next-auth.session-token"}
)
PLAYWRIGHT_REQUEST_TIMEOUT_MS = 30000
REQUESTS_TIMEOUT_SEC = 30


class NintendoAuthError(Exception):
    pass


class NintendoCaptureError(Exception):
    pass


class NintendoEndpointError(Exception):
    pass


def _looks_like_html(resp):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype:
        return True
    head = (resp.text or "")[:200].lstrip().lower()
    return head.startswith("<!doctype") or head.startswith("<html")


def _is_transactions_graphql_url(url):
    u = url or ""
    return "graphql" in u and "TransactionsClientRootClient" in u


def _response_text(resp):
    text_attr = getattr(resp, "text", "")
    if callable(text_attr):
        return text_attr() or ""
    return text_attr or ""


def _merge_graphql_payload(payload, collected, seen_ids):
    histories = payload.get("data", {}).get("account", {}).get("transactionHistories", {})
    batch = histories.get("transactionHistories")
    if not isinstance(batch, list):
        return 0
    added = 0
    for item in batch:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("transactionId") or "")
        if tid and tid in seen_ids:
            continue
        if tid:
            seen_ids.add(tid)
        collected.append(item)
        added += 1
    return added


def _drain_graphql_candidates(candidates, collected, seen_ids):
    added = 0
    while candidates:
        resp = candidates.pop(0)
        try:
            payload = json.loads(resp.text())
        except (ValueError, TypeError, RuntimeError):
            continue
        added += _merge_graphql_payload(payload, collected, seen_ids)
    return added


def probe_session_id_token(http_get, *, timeout=REQUESTS_TIMEOUT_SEC):
    out = {"ok": False, "status": None, "id_token_present": False, "error": None}
    try:
        resp = http_get(SESSION_URL, timeout=timeout)
        status = int(getattr(resp, "status", 0) or 0)
        out["status"] = status
        if status != 200:
            out["error"] = f"HTTP {resp.status}"
            return out
        body = json.loads(_response_text(resp))
        out["id_token_present"] = bool(body.get("idToken"))
        out["ok"] = out["id_token_present"]
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


class NintendoClient:
    def __init__(self, cookie_header="", *, profile_path=None, user_agent=None, headless=True, dump_debug_path=None):
        self._cookie = (cookie_header or "").strip()
        self._profile_path = profile_path
        self._user_agent = (
            user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        self._headless = headless
        self._dump_debug_path = dump_debug_path

    def fetch_all_transactions(self):
        if self._profile_path and self._profile_path.exists():
            return self._fetch_via_browser_profile(self._profile_path)
        if self._cookie:
            return self._fetch_via_cookie_requests()
        raise NintendoAuthError(
            "Nintendo is not connected. Open Connections, connect Nintendo, and complete sign-in on ec.nintendo.com (transactions page)."
        )

    def _fetch_via_cookie_requests(self):
        session = requests.Session()
        session.headers.update(
            {
                "Cookie": self._cookie,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": TRANSACTIONS_PAGE,
                "Origin": "https://ec.nintendo.com",
                "User-Agent": self._user_agent,
            }
        )
        auth = session.get(SESSION_URL, timeout=REQUESTS_TIMEOUT_SEC)
        if auth.status_code in (401, 403):
            raise NintendoAuthError(
                f"Nintendo rejected the session ({auth.status_code}). Reconnect Nintendo in Connections."
            )
        if not auth.ok:
            raise NintendoAuthError(
                f"Could not load Nintendo session ({auth.status_code}). Reconnect Nintendo in Connections."
            )
        try:
            body = auth.json()
        except ValueError as exc:
            raise NintendoAuthError("Nintendo session response was not JSON — reconnect in Connections.") from exc
        if not body.get("idToken"):
            raise NintendoAuthError(
                "Nintendo cookie is incomplete (no idToken). Reconnect Nintendo in Connections so the full eShop session is saved to the browser profile."
            )
        raise NintendoAuthError(
            "Nintendo now requires the saved browser profile for purchase history. Reconnect Nintendo in Connections, then run the fetcher again."
        )

    def _graphql_batch_len(self, payload):
        batch = payload.get("data", {}).get("account", {}).get("transactionHistories", {}).get("transactionHistories")
        return len(batch) if isinstance(batch, list) else 0

    def _fetch_via_direct_graphql(self, context, collected, seen_ids):
        probe = probe_session_id_token(context.request.get, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS)
        if not probe.get("ok"):
            return 0
        session_resp = context.request.get(SESSION_URL, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS)
        try:
            session_body = json.loads(session_resp.text())
        except (ValueError, TypeError):
            return 0
        id_token = session_body.get("idToken")
        if not id_token:
            return 0
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": TRANSACTIONS_PAGE,
            "Origin": "https://ec.nintendo.com",
            "User-Agent": self._user_agent,
            "Authorization": f"Bearer {id_token}",
        }
        rows_before = len(collected)
        page_num = 1
        for _ in range(200):
            variables = json.dumps({"page": page_num, "limit": PAGE_SIZE}, separators=(",", ":"))
            extensions = json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": PERSISTED_QUERY_HASH}}, separators=(",", ":")
            )
            query = urlencode(
                {"operationName": "TransactionsClientRootClient", "variables": variables, "extensions": extensions}
            )
            url = f"{GRAPHQL_URL}?{query}"
            resp = context.request.get(url, headers=headers, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS)
            if resp.status != 200:
                break
            try:
                payload = json.loads(resp.text())
            except (ValueError, TypeError):
                break
            batch_len = self._graphql_batch_len(payload)
            _merge_graphql_payload(payload, collected, seen_ids)
            if batch_len == 0:
                break
            page_num += 1
            time.sleep(0.3)
        return len(collected) - rows_before

    def _write_debug(self, debug):
        if not self._dump_debug_path:
            return
        try:
            self._dump_debug_path.parent.mkdir(parents=True, exist_ok=True)
            self._dump_debug_path.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _fetch_via_browser_profile(self, profile_path):
        from auth.cdp_browser import launch_persistent_profile

        collected = []
        seen_ids = set()
        candidates = []
        debug = {
            "profile": str(profile_path),
            "headless": self._headless,
            "graphql_candidates_seen": 0,
            "graphql_rows_merged": 0,
            "session_probe": None,
            "final_url": None,
            "page_title": None,
            "login_page_detected": False,
            "direct_fallback_rows": 0,
        }

        def on_response(resp):
            url = getattr(resp, "url", "") or ""
            if not _is_transactions_graphql_url(url):
                return
            if getattr(resp, "status", 0) != 200:
                return
            candidates.append(resp)
            debug["graphql_candidates_seen"] = debug.get("graphql_candidates_seen", 0) + 1

        with launch_persistent_profile(profile_path, headless=self._headless) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", on_response)
            try:
                page.goto(TRANSACTIONS_PAGE, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                raise NintendoAuthError(f"Could not open Nintendo transactions page: {exc}") from exc
            time.sleep(6)
            debug["graphql_rows_merged"] = _drain_graphql_candidates(candidates, collected, seen_ids)
            time.sleep(6)
            debug["graphql_rows_merged"] += _drain_graphql_candidates(candidates, collected, seen_ids)
            self._paginate_transactions_ui(page)
            time.sleep(3)
            debug["graphql_rows_merged"] += _drain_graphql_candidates(candidates, collected, seen_ids)
            debug["session_probe"] = probe_session_id_token(context.request.get, timeout=PLAYWRIGHT_REQUEST_TIMEOUT_MS)
            try:
                debug["final_url"] = page.url
                debug["page_title"] = page.title()
            except Exception:
                pass
            debug["direct_fallback_rows"] = self._fetch_via_direct_graphql(context, collected, seen_ids)
            if not collected:
                html = ""
                try:
                    html = page.content().lower()
                except Exception:
                    pass
                debug["login_page_detected"] = "log in" in html or "sign up" in html
                self._write_debug(debug)
                if debug["login_page_detected"]:
                    raise NintendoAuthError("Nintendo session expired — open Connections and reconnect Nintendo.")
                raise NintendoCaptureError(
                    "Purchase history could not be captured from the transactions page. Try: python fetch_nintendo.py --skip-hltb --headed --dump-debug (see cache/nintendo/fetch_debug.json). Reconnect in Connections if the headed browser shows a sign-in page."
                )
        self._write_debug(debug)
        return [_map_graphql_item(item) for item in collected]

    def _paginate_transactions_ui(self, page):
        try:
            labels = page.evaluate(
                "() => [...document.querySelectorAll('button, a')]\n                    .map(el => (el.innerText || '').trim())\n                    .filter(t => /^\\d+$/.test(t))\n                    .map(t => parseInt(t, 10))\n                    .filter(n => n > 1)"
            )
        except Exception:
            return
        if not isinstance(labels, list):
            return
        for page_num in sorted(set(int(x) for x in labels if isinstance(x, (int, float)))):
            try:
                page.evaluate(
                    f"() => {{\n                        const want = {page_num};\n                        const el = [...document.querySelectorAll('button, a')]\n                            .find(n => (n.innerText || '').trim() === String(want));\n                        if (el) el.click();\n                    }}"
                )
            except Exception:
                continue
            time.sleep(2.5)


def _map_graphql_item(item):
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
