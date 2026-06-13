"""Post free-claim announcements to Discord via maintainer-configured webhooks."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from shared.free_claims_sources import GAMERPOWER_ATTRIBUTION
from shared.steam_match import strip_giveaway_decorations

CLAIM_LINK = "https://baklog.app"

# Public community webhook (non-members). Gets the closed-beta invite copy.
ALTAR_WEBHOOK_NAME = "Sacrificial Altar"
BETA_INVITE_LINE = f"BAKLOG is in closed beta. Request an invite at {CLAIM_LINK}"

_WEBHOOK_ENV = (
    ("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "Sacrificial Altar"),
    ("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", "BAKLOG Discord"),
)

_MAX_POST_ATTEMPTS = 4
_MAX_RETRY_SLEEP_S = 5.0
_DISCORD_FIELD_VALUE_MAX = 1024


def validate_claim_item_for_discord(item: dict[str, Any]) -> str | None:
    if not isinstance(item, dict):
        return "item must be an object"
    for field in ("id", "store", "title"):
        if not str(item.get(field) or "").strip():
            return f"item missing {field}"
    return None


def _is_webhook_url(url: str) -> bool:
    u = str(url or "").strip()
    return u.startswith("http://") or u.startswith("https://")


def load_webhooks() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for env_key, name in _WEBHOOK_ENV:
        url = str(os.environ.get(env_key) or "").strip()
        if url and _is_webhook_url(url):
            out.append({"name": name, "url": url})
    return out


def _clamp_field_value(value: str) -> str:
    return str(value or "")[:_DISCORD_FIELD_VALUE_MAX]


def _format_ends_at(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%b %d, %Y")


def _display_title(item: dict[str, Any]) -> str:
    title = strip_giveaway_decorations(str(item.get("title") or "")).strip()
    return title or str(item.get("id") or "Free game")


def _display_store(item: dict[str, Any]) -> str:
    store = str(item.get("store") or "").strip().lower()
    if not store:
        return "Unknown"
    return store.replace("_", " ").title()


def _claim_url(item: dict[str, Any]) -> str:
    url = str(item.get("claim_url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url[:2048]
    return ""


def build_discord_payload(
    item: dict[str, Any], *, include_beta_invite: bool = False
) -> dict[str, Any]:
    """Build a Discord webhook JSON body for one claim.

    The embed links to the real store claim URL when present (falling back to
    the BAKLOG site). When ``include_beta_invite`` is set, the content adds a
    closed-beta invite line for the public Altar audience; members' server gets
    the plain claim post.
    """
    title = _display_title(item)
    claim_url = _claim_url(item)
    link = claim_url or CLAIM_LINK
    fields: list[dict[str, Any]] = [
        {
            "name": "Store",
            "value": _clamp_field_value(_display_store(item)),
            "inline": True,
        },
    ]
    ends_label = _format_ends_at(item.get("ends_at"))
    if ends_label:
        fields.append(
            {
                "name": "Ends",
                "value": _clamp_field_value(ends_label),
                "inline": True,
            }
        )

    embed: dict[str, Any] = {
        "title": title[:256],
        "url": link,
        "fields": fields,
    }
    header_image = str(item.get("header_image") or "").strip()
    if header_image.startswith("http://") or header_image.startswith("https://"):
        embed["thumbnail"] = {"url": header_image[:2048]}

    if claim_url:
        content_lines = [f"Free game, claim it here: {claim_url}"]
    else:
        content_lines = [f"Free game on BAKLOG: {CLAIM_LINK}"]
    if include_beta_invite:
        content_lines.append(BETA_INVITE_LINE)

    payload: dict[str, Any] = {
        "content": "\n".join(content_lines),
        "embeds": [embed],
    }
    if str(item.get("source") or "").strip().lower() == "gamerpower":
        embed["footer"] = {"text": GAMERPOWER_ATTRIBUTION}
    return payload


def _post_webhook_once(
    url: str, body: dict[str, Any]
) -> tuple[int, str, float | None, bool]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "BAKLOG-claims-discord/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None, False
    except urllib.error.HTTPError as exc:
        retry_after: float | None = None
        rate_limit_global = False
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            try:
                parsed = json.loads(detail or "{}")
                retry_after = float(parsed.get("retry_after") or 1.0)
                rate_limit_global = bool(parsed.get("global"))
            except (TypeError, ValueError, json.JSONDecodeError):
                retry_after = 1.0
        return exc.code, detail, retry_after, rate_limit_global
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, f"network error: {exc}", None, False


def post_to_webhook(url: str, body: dict[str, Any]) -> dict[str, Any]:
    last_error = "unknown error"
    status = 0
    for attempt in range(_MAX_POST_ATTEMPTS):
        status, detail, retry_after, rate_limit_global = _post_webhook_once(url, body)
        if 200 <= status < 300:
            return {"ok": True, "status": status}
        last_error = detail.strip() or f"HTTP {status}"
        if (
            status == 429
            and retry_after is not None
            and attempt + 1 < _MAX_POST_ATTEMPTS
            and not rate_limit_global
            and retry_after <= _MAX_RETRY_SLEEP_S
        ):
            time.sleep(min(max(retry_after, 0.5), _MAX_RETRY_SLEEP_S))
            continue
        break
    return {"ok": False, "status": status, "error": last_error[:500]}


def post_claim_to_discord(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Post one claim embed to every configured webhook.

    The public Altar webhook gets closed-beta invite copy; other targets get the
    plain claim post.
    """
    results: list[dict[str, Any]] = []
    for target in load_webhooks():
        include_beta_invite = target["name"] == ALTAR_WEBHOOK_NAME
        body = build_discord_payload(item, include_beta_invite=include_beta_invite)
        posted = post_to_webhook(target["url"], body)
        results.append({"name": target["name"], **posted})
    return results
