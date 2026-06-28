"""Prime Gaming claims via Luna (browser session replay).

Reads ``data.claims.claims[]`` from Luna GraphQL responses after the user signs in
on Connections (persistent profile at ``cache/auth/profiles/amazon_web``).

Filter (codeless / Amazon-fulfilled only):
- Drop claims with ``destinationAccountType`` in a known external launcher set
  (EPIC, STEAM, GOG, …) — these are redemption-key giveaways.
- Drop claims with any redemption/code field populated.
- Keep claims with a title and no external destination (Amazon Games delivery).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from shared.profile_paths import profile_cache_dir

LUNA_CLAIMS_URL = "https://luna.amazon.com/claims/my-collection"
GAMING_HOME_URL = "https://gaming.amazon.com/home"
PROFILE_KEY = "amazon_web"

# Ordered collection targets after sign-in (Luna first, gaming.amazon.com fallback).
COLLECTION_URLS: tuple[str, ...] = (LUNA_CLAIMS_URL, GAMING_HOME_URL)

AMAZON_WEB_HUB_REDIRECT_SEC = 3
AMAZON_WEB_RENUDGE_SEC = 15

_OPENID_IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
_OPENID_NS = "http://specs.openid.net/auth/2.0"

_AMAZON_SESSION_COOKIE_NAMES = frozenset({
    "session-id",
    "session-id-time",
    "at-main",
    "sess-at-main",
    "ubid-main",
    "session-token",
    "x-main",
})

_AMAZON_HOST_MARKERS = ("amazon.com", "luna.amazon.com", "gaming.amazon.com")

# External launcher targets from Prime Gaming key drops (user DevTools sample: EPIC).
_EXTERNAL_DESTINATION_TYPES = frozenset({
    "EPIC",
    "STEAM",
    "GOG",
    "UBISOFT",
    "BATTLENET",
    "BLIZZARD",
    "ORIGIN",
    "EA",
    "XBOX",
    "MICROSOFT",
    "NINTENDO",
    "RIOT",
    "ROCKSTAR",
    "BETHESDA",
    "HUMBLE",
    "ITCH",
})

_CODE_FIELD_NAMES = (
    "redemptionCode",
    "gameCode",
    "claimCode",
    "activationCode",
    "code",
)

_IMAGE_FIELD_CANDIDATES = (
    "imageUrl",
    "productImageUrl",
    "iconUrl",
    "thumbnailUrl",
    "boxArtUrl",
)

_DATE_FIELD_CANDIDATES = (
    "claimDate",
    "orderDate",
    "purchaseDate",
    "createdDate",
    "fulfillmentDate",
)


class AmazonWebAuthError(Exception):
    """Prime Gaming web session could not be read."""


class AmazonWebError(Exception):
    """Prime Gaming claims could not be parsed."""


_RAW_DUMP_BASENAME = "amazon_web_raw.json"
_RAW_DUMP_MAX_AGE_S = 60 * 60 * 24 * 7  # used by fetcher fallback
_RAW_FAILURE_DUMP_BASENAME = "amazon_web_raw_failure.json"


def raw_dump_path() -> Path:
    return profile_cache_dir() / _RAW_DUMP_BASENAME


def raw_failure_dump_path() -> Path:
    return profile_cache_dir() / _RAW_FAILURE_DUMP_BASENAME


def raw_dump_max_age_s() -> int:
    return int(_RAW_DUMP_MAX_AGE_S)


def classify_sniff_capture(*, capture_ok: bool, signed_in: bool) -> str:
    """Classify the sniff result without depending on browser runtime."""
    if capture_ok:
        return "claims_captured"
    return "signed_out" if not signed_in else "signed_in_no_claims"


def _now_s() -> float:
    return time.time()


def collection_urls() -> tuple[str, ...]:
    """URLs to open so Prime Gaming loads the claims GraphQL payload."""
    return COLLECTION_URLS


def amazon_signin_url(return_to: str = LUNA_CLAIMS_URL) -> str:
    """Stable Amazon OpenID sign-in URL (no single-use ``ssoResponse`` token)."""
    params = {
        "openid.pape.max_auth_age": "3600",
        "openid.return_to": return_to,
        "openid.identity": _OPENID_IDENTIFIER_SELECT,
        "openid.assoc_handle": "tempo_us",
        "openid.mode": "checkid_setup",
        "language": "en_US",
        "openid.claimed_id": _OPENID_IDENTIFIER_SELECT,
        "pageId": "tempo_us",
        "openid.ns": _OPENID_NS,
    }
    return f"https://www.amazon.com/ap/signin?{urlencode(params)}"


def prime_goto_signin(page: Any, return_to: str = LUNA_CLAIMS_URL) -> str:
    """Open Amazon sign-in with ``return_to`` defaulting to My Collection."""
    target = amazon_signin_url(return_to)
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass
    return target


def is_signin_url(url: str) -> bool:
    u = (url or "").lower()
    if "signin" in u or "sign-in" in u:
        return True
    if "/ap/signin" in u or "/ap/register" in u:
        return True
    return "/ap/" in u and "sign" in u


def has_amazon_session_cookies(context: Any) -> bool:
    """True when the profile has Amazon session cookies (post sign-in)."""
    try:
        cookies = context.cookies()
    except Exception:
        return False
    for c in cookies:
        name = (c.get("name") or "").lower()
        domain = (c.get("domain") or "").lower()
        if "amazon" not in domain:
            continue
        if name in _AMAZON_SESSION_COOKIE_NAMES or name.startswith("session"):
            if c.get("value"):
                return True
    return False


def signed_in(url: str, context: Any) -> bool:
    """True when the user appears signed in to Amazon (not on a sign-in page)."""
    if is_signin_url(url):
        return False
    if not has_amazon_session_cookies(context):
        return False
    u = (url or "").lower()
    return any(marker in u for marker in _AMAZON_HOST_MARKERS)


def is_luna_hub(url: str) -> bool:
    """True on ``luna.amazon.com/`` (post-login hub), not My Collection."""
    u = (url or "").lower()
    if "luna.amazon.com" not in u:
        return False
    parsed = urlparse(url or "")
    path = (parsed.path or "/").rstrip("/") or "/"
    return path == "/"


def on_collection_page(url: str) -> bool:
    """True when the browser is on a Prime Gaming library / My Collection surface."""
    u = (url or "").lower()
    if is_luna_hub(url):
        return False
    if "my-collection" in u or "/claims/" in u:
        return True
    if "luna.amazon.com" in u and "claim" in u:
        return True
    if "gaming.amazon.com" in u:
        return True
    return False


def needs_collection_redirect(url: str, context: Any) -> bool:
    """Signed in but not on a loaded collection surface (e.g. Luna hub)."""
    return signed_in(url, context) and (is_luna_hub(url) or not on_collection_page(url))


def is_luna_error_page(html: str) -> bool:
    lower = (html or "").lower()
    return (
        "technical difficulties" in lower
        or "having issues with our service" in lower
        or "please come back later" in lower
    )


def collection_page_ready(html: str, url: str) -> bool:
    """Collection URL loaded without sign-in or Luna outage banner."""
    if is_signin_url(url) or not on_collection_page(url):
        return False
    if is_luna_error_page(html):
        return False
    return True


def prime_goto_collection(page: Any, url_index: int = 0) -> str:
    """Navigate to a collection URL; return the URL attempted."""
    urls = collection_urls()
    target = urls[min(url_index, len(urls) - 1)]
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=25_000)
    except Exception:
        pass
    return target


def try_parse_claims_from_html(html: str) -> list[dict[str, Any]] | None:
    """Parse claims from raw JSON or embedded ``data.claims`` in page HTML."""
    body = (html or "").strip()
    if not body:
        return None
    direct = try_parse_claims_from_text(body)
    if direct:
        return direct
    if '"claims"' not in body and "'claims'" not in body:
        return None
    start = body.find('{"data"')
    while start >= 0:
        depth = 0
        for end in range(start, min(start + 500_000, len(body))):
            ch = body[end]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = body[start : end + 1]
                    items = try_parse_claims_from_text(chunk)
                    if items is not None:
                        return items
                    break
        start = body.find('{"data"', start + 1)
    return None


def claims_visible_in_body(body: str) -> bool:
    return try_parse_claims_from_html(body) is not None


def try_parse_claims_from_text(body: str) -> list[dict[str, Any]] | None:
    """Return claims list if *body* is JSON with ``data.claims.claims``."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return extract_claims_list(data)


def extract_claims_list(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    claims_root = data.get("claims")
    if isinstance(claims_root, dict):
        items = claims_root.get("claims")
        if isinstance(items, list):
            return [c for c in items if isinstance(c, dict)]
    if isinstance(claims_root, list):
        return [c for c in claims_root if isinstance(c, dict)]
    return None


def scrub_claim_codes(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return shallow copies of ``claims`` with redemption/activation code fields
    removed.

    Raw Amazon claim payloads can carry one-time redemption/game/claim/activation
    codes (see ``_CODE_FIELD_NAMES``). Those are credentials and must never be
    written to the on-disk raw dump used as a headless fetcher fallback.
    """
    cleaned: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            cleaned.append(claim)
            continue
        copy = {k: v for k, v in claim.items() if k not in _CODE_FIELD_NAMES}
        cleaned.append(copy)
    return cleaned


def _has_redemption_code(claim: dict[str, Any]) -> bool:
    for key in _CODE_FIELD_NAMES:
        val = claim.get(key)
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            return True
        if val:
            return True
    return False


def is_codeless_claim(claim: dict[str, Any]) -> bool:
    """True when the claim is Amazon-fulfilled (not an external key drop)."""
    title = (claim.get("itemTitle") or claim.get("title") or "").strip()
    if not title:
        return False
    dest_type = (claim.get("destinationAccountType") or "").strip().upper()
    if dest_type in _EXTERNAL_DESTINATION_TYPES:
        return False
    if _has_redemption_code(claim):
        return False
    state = (claim.get("orderState") or "").strip().upper()
    if state in ("CANCELLED", "CANCELED", "EXPIRED", "REVOKED"):
        return False
    return True


def _pick_image(claim: dict[str, Any]) -> str | None:
    for key in _IMAGE_FIELD_CANDIDATES:
        url = claim.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _pick_date(claim: dict[str, Any]) -> str | None:
    for key in _DATE_FIELD_CANDIDATES:
        raw = claim.get(key)
        if not raw:
            continue
        if isinstance(raw, str):
            if "T" in raw:
                return raw.split("T")[0]
            return raw[:10] if len(raw) >= 10 else raw
    return None


def claim_to_record(claim: dict[str, Any]) -> dict[str, Any] | None:
    if not is_codeless_claim(claim):
        return None
    title = (claim.get("itemTitle") or claim.get("title") or "").strip()
    product_id = (
        claim.get("itemId")
        or claim.get("offerId")
        or claim.get("orderId")
    )
    if not product_id:
        return None
    product_id = str(product_id)
    icon = _pick_image(claim)
    release = _pick_date(claim)
    store_url = f"https://www.amazon.com/s?k={quote(title)}&i=videogames"
    return {
        "amazon_product_id": product_id,
        "amazon_entitlement_id": claim.get("orderId"),
        "amazon_adg_id": None,
        "name": title,
        "asin": claim.get("productAsin") or claim.get("asin"),
        "product_sku": None,
        "product_line": "prime_claim",
        "header_image": icon,
        "library_image": icon,
        "genres": [],
        "release_date": release,
        "last_played": None,
        "store_url": store_url,
        "publisher": None,
        "prime_claim_order_state": claim.get("orderState"),
    }


def filter_codeless_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for claim in claims:
        rec = claim_to_record(claim)
        if not rec:
            continue
        pid = rec["amazon_product_id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        records.append(rec)
    return sorted(records, key=lambda r: r["name"].lower())


def _response_may_contain_claims(url: str) -> bool:
    u = (url or "").lower()
    return "graphql" in u or ("amazon" in u and "claims" in u)


def _capture_claims_from_response(
    resp: Any,
    candidates: list[Any],
    raw_claims: list[dict[str, Any]],
    captured: dict[str, bool],
) -> None:
    """Response handler (CDP reader thread): NEVER read body here.

    The CDP driver dispatches response handlers on the same single reader thread
    that pumps command replies. Calling resp.text() (Network.getResponseBody)
    here would deadlock by waiting on the reader thread to deliver its own
    response. Instead, enqueue candidate responses and let the polling loop
    parse bodies on a non-reader thread.
    """
    if captured["done"]:
        return
    try:
        if getattr(resp, "status", 0) != 200:
            return
        url = (getattr(resp, "url", None) or "").lower()
        if not _response_may_contain_claims(url):
            return
        candidates.append(resp)
    except Exception:
        pass


def _drain_claim_candidates(
    candidates: list[Any],
    raw_claims: list[dict[str, Any]],
    captured: dict[str, bool],
    *,
    max_per_tick: int = 6,
) -> bool:
    """Poll thread: parse queued candidate responses and capture claims.

    Returns True when capture criteria are met.
    """
    if captured.get("done"):
        return True
    drained = 0
    while candidates and drained < max_per_tick and not captured.get("done"):
        drained += 1
        resp = candidates.pop(0)
        try:
            items = try_parse_claims_from_text(resp.text())
        except Exception:
            items = None
        if items is not None:
            raw_claims.clear()
            raw_claims.extend(items)
            captured["done"] = True
            captured["claims_captured"] = True
            return True
    return bool(captured.get("done"))


def _try_capture_from_page_html(
    html: str,
    url: str,
    context: Any,
    raw_claims: list[dict[str, Any]],
    captured: dict[str, bool],
    *,
    allow_session_only: bool,
    session_only_grace_ok: bool,
) -> bool:
    """Return True when connect/fetch capture criteria are met."""
    items = try_parse_claims_from_html(html)
    if items is not None:
        raw_claims.clear()
        raw_claims.extend(items)
        captured["done"] = True
        captured["claims_captured"] = True
        return True
    if (
        allow_session_only
        and session_only_grace_ok
        and collection_page_ready(html, url)
        and signed_in(url, context)
    ):
        captured["done"] = True
        captured["session_only_captured"] = True
        return True
    return False


def _collection_redirect_interval(url: str, html: str) -> float:
    if is_luna_hub(url) or is_luna_error_page(html):
        return AMAZON_WEB_HUB_REDIRECT_SEC
    return AMAZON_WEB_RENUDGE_SEC


def _next_collection_index(url_idx: int, url: str, html: str) -> int:
    if is_luna_error_page(html):
        return 1 if len(COLLECTION_URLS) > 1 else 0
    if is_luna_hub(url):
        return 0
    return (url_idx + 1) % len(COLLECTION_URLS)


def _poll_prime_collection(
    page: Any,
    context: Any,
    *,
    deadline: float,
    candidates: list[Any],
    raw_claims: list[dict[str, Any]],
    captured: dict[str, bool],
    allow_session_only: bool = False,
    session_only_grace_s: float = 8.0,
    start_at_signin: bool = False,
    session: Any = None,
    poll_interval_ms: int = 500,
    log_progress: bool = False,
    log_prefix: str = "Amazon web",
) -> None:
    """Navigate sign-in / collection until claims or session criteria are met."""
    if start_at_signin and not signed_in(page.url or "", context):
        prime_goto_signin(page)
    else:
        prime_goto_collection(page, 0)
    last_goto = time.time()
    last_hint = 0.0
    nudged = False
    url_idx = 0
    poll_t0 = _now_s()
    last_log = 0.0
    while _now_s() < deadline and not captured["done"]:
        _drain_claim_candidates(candidates, raw_claims, captured)
        if captured["done"]:
            break
        url = page.url or ""
        now = _now_s()
        try:
            html = page.content()
        except Exception:
            html = ""
        session_only_grace_ok = (
            (not allow_session_only) or (now - poll_t0 >= session_only_grace_s)
        )
        if _try_capture_from_page_html(
            html,
            url,
            context,
            raw_claims,
            captured,
            allow_session_only=allow_session_only,
            session_only_grace_ok=session_only_grace_ok,
        ):
            break

        si = signed_in(url, context)
        if (
            log_progress
            and session is None
            and now - last_log >= 10
        ):
            last_log = now
            state = (
                "signin"
                if is_signin_url(url)
                else ("luna_hub" if is_luna_hub(url) else "collection")
            )
            print(
                f"{log_prefix}: poll state={state} signed_in={si} url={url}",
                flush=True,
            )
        if si and not nudged:
            nudged = True
            if session is not None:
                session.emit("signed_in", {"url": url or LUNA_CLAIMS_URL})
            try:
                page.bring_to_front()
            except Exception:
                pass
            prime_goto_collection(page, 0)
            last_goto = now
            url_idx = 0
        elif si and needs_collection_redirect(url, context):
            interval = _collection_redirect_interval(url, html)
            if now - last_goto >= interval:
                url_idx = _next_collection_index(url_idx, url, html)
                prime_goto_collection(page, url_idx)
                last_goto = now

        if session is not None and now - last_hint > 10:
            last_hint = now
            if is_signin_url(url):
                msg = "Sign in to your Amazon account in the browser window."
            elif is_luna_error_page(html):
                msg = (
                    "Prime Gaming (Luna) is having issues — trying gaming.amazon.com instead. "
                    "You can also wait and retry later."
                )
            elif si and is_luna_hub(url):
                msg = "Signed in — opening My Collection…"
            elif si and not on_collection_page(url):
                msg = "Signed in — opening Prime Gaming My Collection…"
            elif si:
                msg = "Keep the window open until My Collection finishes loading."
            else:
                msg = (
                    "Sign in on the Amazon page — we'll send you to My Collection after login."
                )
            session.emit("waiting_for_user", {"message": msg})

        page.wait_for_timeout(poll_interval_ms)


def sniff_claims(
    *,
    timeout_s: int = 60,
    dump_path: Path | str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Replay saved browser profile; return (raw_claims, records, outcome)."""
    from auth.cdp_browser import launch_persistent_profile
    from auth.secrets import profile_dir

    profile = profile_dir(PROFILE_KEY)
    if not profile.is_dir():
        raise AmazonWebAuthError(
            "No saved Prime Gaming web profile. "
            "Open Connections and connect “Amazon (Prime Gaming, web)” first."
        )

    raw_claims: list[dict[str, Any]] = []
    candidates: list[Any] = []

    def _outcome_template() -> dict[str, Any]:
        return {
            "capture_ok": False,
            "claims_captured": False,
            "session_only_captured": False,
            "signed_in": False,
            "final_url": None,
            "headless": True,
            "reason": None,
        }

    def _dump_raw(reason: str, *, forced_path: Path | None = None) -> None:
        from shared.raw_dumps import raw_dumps_enabled

        if forced_path is None and dump_path is None and not raw_dumps_enabled():
            return
        path = forced_path or (Path(dump_path) if dump_path is not None else None)
        if path is None:
            # Do not overwrite the connect-time fallback dump (amazon_web_raw.json).
            # We still write a diagnostic dump for observability.
            path = raw_failure_dump_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "urls": list(COLLECTION_URLS),
                    "raw_claim_count": len(raw_claims),
                    "raw_claims": raw_claims,
                    "codeless_count": len(filter_codeless_claims(raw_claims)),
                    "capture_reason": reason,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _run_once(*, headless: bool, run_timeout_s: int) -> dict[str, Any]:
        # Reset shared buffers between retries.
        candidates.clear()
        raw_claims.clear()

        captured: dict[str, bool] = {
            "done": False,
            "claims_captured": False,
            "session_only_captured": False,
        }

        def _on_response(resp: Any) -> None:
            _capture_claims_from_response(resp, candidates, raw_claims, captured)

        outcome = _outcome_template()
        outcome["headless"] = headless
        outcome["signed_in"] = False
        outcome["final_url"] = None

        deadline = _now_s() + run_timeout_s
        with launch_persistent_profile(str(profile), headless=headless) as ctx:
            # Parity with Connections-headed auth.
            from auth.cdp_browser import STEALTH_INIT_SCRIPT

            ctx.add_init_script(STEALTH_INIT_SCRIPT)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", _on_response)
            _poll_prime_collection(
                page,
                ctx,
                deadline=deadline,
                candidates=candidates,
                raw_claims=raw_claims,
                captured=captured,
                allow_session_only=False,
                start_at_signin=False,
                log_progress=True,
                log_prefix="Amazon web",
            )

            final_url = page.url or ""
            outcome["final_url"] = final_url
            outcome["signed_in"] = signed_in(final_url, ctx)
            outcome["claims_captured"] = captured.get("claims_captured", False)
            outcome["session_only_captured"] = captured.get(
                "session_only_captured", False
            )
            outcome["capture_ok"] = captured.get("claims_captured", False)
            outcome["reason"] = (
                "claims_captured"
                if outcome["capture_ok"]
                else ("session_only" if captured.get("session_only_captured") else "no_claims")
            )

            print(
                f"Amazon web: final headless={headless} capture_ok={outcome['capture_ok']} "
                f"claims_captured={outcome['claims_captured']} signed_in={outcome['signed_in']} "
                f"reason={outcome['reason']} url={final_url}",
                flush=True,
            )

        return outcome

    headless_timeout_s = min(timeout_s, 30)
    headed_timeout_s = min(timeout_s, 25)

    # 1) Headless first (faster, usually works for already-connected profiles).
    headless_outcome = _run_once(headless=True, run_timeout_s=headless_timeout_s)
    if headless_outcome["capture_ok"]:
        return raw_claims, filter_codeless_claims(raw_claims), headless_outcome

    # 2) If headless captured nothing, record diagnostics (raw dump) and fall
    # back to headed once for parity (matches working headed Connect window).
    _dump_raw("headless_no_claims")
    headless_outcome["reason"] = headless_outcome.get("reason") or "no_claims"

    # Signed-out vs signed-in-no-claims.
    if not headless_outcome["signed_in"]:
        raise AmazonWebAuthError(
            "Could not capture Prime Gaming claims — session may have expired. "
            "Reconnect “Amazon (Prime Gaming, web)” on Connections."
        )

    # 3) Visible retry (diagnostic parity). This may pop a window.
    headed_outcome = _run_once(headless=False, run_timeout_s=headed_timeout_s)
    if headed_outcome["capture_ok"]:
        # Preserve headed capture; overwrite raw dump with real payload.
        _dump_raw("headed_no_claims_or_captured", forced_path=raw_dump_path())
        return raw_claims, filter_codeless_claims(raw_claims), headed_outcome

    _dump_raw("headed_no_claims")
    return raw_claims, filter_codeless_claims(raw_claims), headed_outcome


class AmazonWebClient:
    def get_library_records(self) -> list[dict]:
        _raw, records, _outcome = sniff_claims()
        return records
