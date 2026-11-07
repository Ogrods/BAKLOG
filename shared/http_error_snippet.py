"""Short HTTP error snippets for fetcher/client logs (never dump raw HTML)."""

from __future__ import annotations

import re
from typing import Any

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _looks_like_html(text: str, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    if "text/html" in ctype or "application/xhtml" in ctype:
        return True
    stripped = (text or "").lstrip()
    head = stripped[:80].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return True
    if stripped.startswith("<") and "</" in stripped[:500]:
        return True
    return False


def _title_from_html(text: str, *, max_len: int = 80) -> str:
    m = _TITLE_RE.search(text or "")
    if not m:
        return ""
    title = _WS_RE.sub(" ", m.group(1)).strip()
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title


def http_error_snippet(resp: Any, *, max_len: int = 200) -> str:
    """Return a one-line host error for logs - never dump Cloudflare/gateway HTML."""
    status = getattr(resp, "status_code", None)
    if status is None:
        status = getattr(resp, "status", "?")
    headers = getattr(resp, "headers", None) or {}
    try:
        ctype = headers.get("Content-Type") or headers.get("content-type") or ""
    except Exception:
        ctype = ""
    try:
        text = resp.text or ""
    except Exception:
        text = ""
    if _looks_like_html(text, ctype):
        title = _title_from_html(text)
        base = f"HTTP {status} (HTML error page from host)"
        return f"{base}: {title}" if title else base
    snippet = _WS_RE.sub(" ", (text or "")).strip()
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 1].rstrip() + "…"
    return f"HTTP {status}: {snippet}" if snippet else f"HTTP {status}"
