"""Reactive session probes — called after Connect or when a fetcher starts.

These are best-effort checks (GOG may 403 the library API while owned IDs still work).
Tune per provider as we learn what each store accepts from scripted clients.
"""

from __future__ import annotations

from gog_client import GOG_AUTH_MESSAGE, GogAuthError, GogClient

# Providers that have a probe implementation in this module.
PROBEABLE_BROWSER = frozenset({"gog", "xbox_wishlist"})

# Providers whose headed sign-in is authoritative: the connect window confirms
# the session via the live page before closing, so a headless probe miss must
# never veto the connect (xbox.com serves signed-out SSR to headless Chrome
# inconsistently). For these, the probe is advisory — logged, never blocking.
ADVISORY_BROWSER_PROBE = frozenset({"xbox_wishlist"})


def probe_browser_session(provider: str, creds: dict[str, str]) -> str | None:
    """Return an error message when the session looks dead, else None."""
    if provider == "gog":
        return probe_gog_session(creds.get("GOG_AL", ""))
    if provider == "xbox_wishlist":
        return probe_xbox_wishlist_session(creds)
    return None


def probe_xbox_wishlist_session(_creds: dict[str, str]) -> str | None:
    """Verify the saved profile works headlessly (same path as fetch_xbox_wishlist)."""
    from auth.xbox_wishlist_session import (
        capture_xbox_wishlist_preloaded_state,
        validate_xbox_wishlist_state,
    )

    try:
        state = capture_xbox_wishlist_preloaded_state(headless="legacy", timeout_s=25)
    except Exception as exc:  # noqa: BLE001
        return f"Could not verify Xbox wishlist session (headless): {exc}"
    return validate_xbox_wishlist_state(state, headless=True)


def probe_gog_session(gog_al: str) -> str | None:
    """Verify GOG embed APIs accept the gog-al cookie (library or owned-ID fallback)."""
    token = (gog_al or "").strip()
    if not token:
        return "No GOG session cookie captured — sign in at gog.com and try Connect again."
    try:
        GogClient(token).validate_session()
        return None
    except GogAuthError as exc:
        return str(exc) or GOG_AUTH_MESSAGE
