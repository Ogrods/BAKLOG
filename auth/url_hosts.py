"""Hostname allowlist helpers for Connect URL/cookie checks (CodeQL-safe)."""

from __future__ import annotations

from urllib.parse import urlparse


def hostname_of(url_or_host: str) -> str:
    """Return lowercase hostname from a URL or bare host string."""
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    if "://" not in raw and "/" not in raw and "?" not in raw:
        return raw.lstrip(".").lower()
    try:
        host = urlparse(raw if "://" in raw else f"https://{raw}").hostname
    except Exception:  # noqa: BLE001
        return ""
    return (host or "").lower()


def host_matches(url_or_host: str, allowed: str) -> bool:
    """True if hostname equals allowed or is a subdomain (*.allowed)."""
    host = hostname_of(url_or_host)
    allowed = (allowed or "").lstrip(".").lower()
    if not host or not allowed:
        return False
    return host == allowed or host.endswith("." + allowed)


def cookie_domain_matches(domain: str, allowed: str) -> bool:
    """True if a cookie domain belongs to allowed registrable host."""
    host = (domain or "").lstrip(".").lower()
    allowed = (allowed or "").lstrip(".").lower()
    if not host or not allowed:
        return False
    return host == allowed or host.endswith("." + allowed)
