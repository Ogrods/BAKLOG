"""Reactive session probes — called after Connect or when a fetcher starts.

These are best-effort checks (GOG may 403 the library API while owned IDs still work).
Tune per provider as we learn what each store accepts from scripted clients.

Quiet probes (``probe_provider_quiet``) are tri-state and never raise — used by the
Pro background scheduler to flip the connection light without running a fetch.
"""

from __future__ import annotations

from typing import Literal

from clients.gog_client import GOG_AUTH_MESSAGE, GogAuthError, GogClient

from auth.registry import PROVIDERS

ProbeResult = Literal["ok", "auth_fail", "unreachable"]

# Providers that have a probe implementation in this module.
PROBEABLE_BROWSER = frozenset({"gog", "xbox_wishlist"})

# Cheap/no-browser providers eligible for silent hourly health checks.
PROBEABLE_QUIET = frozenset({"gog", "epic", "steam", "itch", "itad"})

# Providers whose headed sign-in is authoritative: the connect window confirms
# the session via the live page before closing, so a headless probe miss must
# never veto the connect (xbox.com serves signed-out SSR to headless Chrome
# inconsistently). For these, the probe is advisory — logged, never blocking.
ADVISORY_BROWSER_PROBE = frozenset(
    k for k, s in PROVIDERS.items() if s.post_connect_probe == "advisory"
)


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


def probe_gog_session_quiet(gog_al: str) -> ProbeResult:
    """Tri-state GOG probe for silent health checks."""
    token = (gog_al or "").strip()
    if not token:
        return "auth_fail"
    try:
        GogClient(token).validate_session()
        return "ok"
    except GogAuthError:
        return "auth_fail"
    except Exception:  # noqa: BLE001 - network/timeout must not flip status
        return "unreachable"


def probe_epic_session_quiet() -> ProbeResult:
    """Tri-state Epic probe: refresh-token exchange only (no library read)."""
    from clients.epic_client import EpicAuthError, EpicClient, EpicCorrectiveActionError

    try:
        client = EpicClient()
        cached = client._load_session()
        if not cached or not cached.get("refresh_token"):
            return "auth_fail"
        client.login()
        return "ok"
    except (EpicAuthError, EpicCorrectiveActionError):
        return "auth_fail"
    except Exception:  # noqa: BLE001
        return "unreachable"


def probe_steam_session_quiet() -> ProbeResult:
    """Tri-state Steam API key probe."""
    from auth.api_keys import _validate_steam
    from auth.manager import resolve_env

    key = resolve_env("STEAM_API_KEY", provider="steam", allow_process_env=False)
    sid = resolve_env("STEAM_ID", provider="steam", allow_process_env=False)
    if not key or not sid:
        return "auth_fail"
    try:
        _validate_steam({"STEAM_API_KEY": key, "STEAM_ID": sid})
        return "ok"
    except RuntimeError:
        return "auth_fail"
    except Exception:  # noqa: BLE001
        return "unreachable"


def probe_itch_session_quiet() -> ProbeResult:
    """Tri-state itch.io API key probe."""
    from auth.api_keys import KEY_INVALID, KEY_VALID, validate_itch_key
    from auth.manager import resolve_env

    key = resolve_env("ITCH_API_KEY", provider="itch", allow_process_env=False)
    if not key:
        return "auth_fail"
    result = validate_itch_key(key)
    if result == KEY_VALID:
        return "ok"
    if result == KEY_INVALID:
        return "auth_fail"
    return "unreachable"


def probe_itad_session_quiet() -> ProbeResult:
    """Tri-state ITAD API key probe."""
    from auth.api_keys import KEY_INVALID, KEY_VALID, validate_itad_key
    from auth.manager import resolve_env

    key = resolve_env("ITAD_API_KEY", provider="itad", allow_process_env=False)
    if not key:
        return "auth_fail"
    result = validate_itad_key(key)
    if result == KEY_VALID:
        return "ok"
    if result == KEY_INVALID:
        return "auth_fail"
    return "unreachable"


def probe_provider_quiet(provider: str) -> ProbeResult:
    """Run a silent tri-state probe for one cheap provider (never raises)."""
    from auth.manager import resolve_env

    if provider == "gog":
        return probe_gog_session_quiet(
            resolve_env("GOG_AL", provider="gog", allow_process_env=False)
        )
    if provider == "epic":
        return probe_epic_session_quiet()
    if provider == "steam":
        return probe_steam_session_quiet()
    if provider == "itch":
        return probe_itch_session_quiet()
    if provider == "itad":
        return probe_itad_session_quiet()
    return "unreachable"
