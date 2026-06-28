from typing import Literal

from clients.gog_client import GOG_AUTH_MESSAGE, GogAuthError, GogClient

ProbeResult = Literal["ok", "auth_fail", "unreachable"]
PROBEABLE_BROWSER = frozenset({"gog", "xbox_wishlist"})
PROBEABLE_QUIET = frozenset({"gog", "epic", "steam", "itch", "itad", "psn"})
ADVISORY_BROWSER_PROBE = frozenset({"xbox_wishlist", "ea"})


def probe_browser_session(provider, creds):
    if provider == "gog":
        return probe_gog_session(creds.get("GOG_AL", ""))
    if provider == "xbox_wishlist":
        return probe_xbox_wishlist_session(creds)
    return None


def probe_xbox_wishlist_session(_creds):
    from auth.xbox_wishlist_session import capture_xbox_wishlist_preloaded_state, validate_xbox_wishlist_state

    try:
        state = capture_xbox_wishlist_preloaded_state(headless="legacy", timeout_s=25)
    except Exception as exc:
        return f"Could not verify Xbox wishlist session (headless): {exc}"
    return validate_xbox_wishlist_state(state, headless=True)


def probe_gog_session(gog_al):
    token = (gog_al or "").strip()
    if not token:
        return "No GOG session cookie captured — sign in at gog.com and try Connect again."
    try:
        GogClient(token).validate_session()
        return None
    except GogAuthError as exc:
        return str(exc) or GOG_AUTH_MESSAGE


def probe_gog_session_quiet(gog_al):
    token = (gog_al or "").strip()
    if not token:
        return "auth_fail"
    try:
        GogClient(token).validate_session()
        return "ok"
    except GogAuthError:
        return "auth_fail"
    except Exception:
        return "unreachable"


def probe_epic_session_quiet():
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
    except Exception:
        return "unreachable"


def probe_steam_session_quiet():
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
    except Exception:
        return "unreachable"


def probe_itch_session_quiet():
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


def probe_itad_session_quiet():
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


def probe_psn_session_quiet():
    from auth.manager import resolve_env
    from clients.psn_client import PsnAuthError, PsnClient

    npsso = resolve_env("PSN_NPSSO", provider="psn", allow_process_env=False)
    if not npsso:
        return "auth_fail"
    try:
        PsnClient(npsso).validate_session()
        return "ok"
    except PsnAuthError:
        return "auth_fail"
    except Exception:
        return "unreachable"


def probe_provider_quiet(provider):
    from auth.manager import resolve_env

    if provider == "gog":
        return probe_gog_session_quiet(resolve_env("GOG_AL", provider="gog", allow_process_env=False))
    if provider == "epic":
        return probe_epic_session_quiet()
    if provider == "steam":
        return probe_steam_session_quiet()
    if provider == "itch":
        return probe_itch_session_quiet()
    if provider == "itad":
        return probe_itad_session_quiet()
    if provider == "psn":
        return probe_psn_session_quiet()
    return "unreachable"
