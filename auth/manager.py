"""Credential resolution, status, and browser-auth orchestration."""

from __future__ import annotations

import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from auth.registry import PROVIDERS, spec_for
from auth.runner import AuthSession, run_browser_auth
from auth.secrets import delete_provider_blob, get_provider_blob, profile_dir, set_provider_blob
from shared.platform_support import platform_supported
from shared.profile_paths import epic_cache_dir

ROOT = Path(__file__).resolve().parents[1]

_active_sessions: dict[str, AuthSession] = {}
_sessions_lock = threading.Lock()


def _migrate_unified_epic() -> None:
    """Split a previously-unified epic blob back into epic + epic_wishlist."""
    epic = get_provider_blob("epic")
    if not epic.get("EPIC_STORE_COOKIE"):
        return
    wl = get_provider_blob("epic_wishlist")
    wl["EPIC_STORE_COOKIE"] = epic["EPIC_STORE_COOKIE"]
    for key in ("status", "connected_at", "last_verified"):
        if epic.get(key) and not wl.get(key):
            wl[key] = epic[key]
    set_provider_blob("epic_wishlist", wl)
    epic.pop("EPIC_STORE_COOKIE", None)
    set_provider_blob("epic", epic)


_migrate_unified_epic()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_fallback(spec_env_keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in spec_env_keys:
        val = os.getenv(key, "").strip()
        if val:
            out[key] = val
    return out


def _merge_creds(provider: str) -> dict[str, str]:
    spec = spec_for(provider)
    blob = get_provider_blob(provider)
    out = _env_fallback(spec.env_keys)
    for key in spec.env_keys:
        val = blob.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    # Legacy single-key aliases
    if provider == "battlenet" and blob.get("BATTLENET_COOKIE"):
        out["BATTLENET_COOKIE"] = blob["BATTLENET_COOKIE"]
    if provider == "nintendo" and blob.get("NINTENDO_COOKIE"):
        out["NINTENDO_COOKIE"] = blob["NINTENDO_COOKIE"]
    return out


def get_credentials(provider: str) -> dict[str, str]:
    return _merge_creds(provider)


def resolve_env(key: str, *, provider: str | None = None) -> str:
    if provider:
        creds = get_credentials(provider)
        if creds.get(key):
            return creds[key]
    for pkey, spec in PROVIDERS.items():
        if key in spec.env_keys:
            creds = get_credentials(pkey)
            if creds.get(key):
                return creds[key]
    return os.getenv(key, "").strip()


def _provider_state(provider: str) -> str:
    """Return one of: connected | unverified | expired | disconnected.

    - "connected" only when the user has explicitly signed in / saved keys
      via the Connections page (stored blob has status=connected).
    - "unverified" when credentials exist only in legacy `.env` and we have
      no record that they currently work. The user should re-sign-in.
    - "expired" when a fetcher previously reported an auth failure.
    - "disconnected" when nothing is available.
    """
    blob = get_provider_blob(provider)
    explicit = blob.get("status")
    spec = spec_for(provider)

    # Platform-restricted providers (e.g. Amazon Games on Windows) must never
    # import their OS-specific client on an unsupported OS — that import raises
    # and would take down GET /api/auth/status for the whole Connections page.
    if not platform_supported(spec.platforms):
        return "unavailable"

    if spec.kind == "local":
        from amazon_client import default_sql_dir

        env_dir = os.getenv("AMAZON_GAMES_SQL_DIR", "").strip() or blob.get("AMAZON_GAMES_SQL_DIR")
        sql_dir = env_dir or str(default_sql_dir())
        return "connected" if Path(sql_dir).is_dir() else "disconnected"

    if explicit == "expired":
        return "expired"
    if explicit == "connected":
        return "connected"

    if spec.kind == "oauth" and provider == "epic":
        session_file = epic_cache_dir() / "session.json"
        if session_file.exists() or os.getenv("EPIC_AUTH_CODE", "").strip():
            return "unverified" if not session_file.exists() else "connected"
        return "disconnected"

    env_has_values = any(os.getenv(k, "").strip() for k in spec.env_keys)
    if env_has_values:
        return "unverified"
    return "disconnected"


def get_status() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, spec in PROVIDERS.items():
        blob = get_provider_blob(key)
        state = _provider_state(key)
        rows.append(
            {
                "key": key,
                "label": spec.label,
                "kind": spec.kind,
                "description": spec.description,
                "tips": list(spec.tips),
                "status": state,
                "connected_at": blob.get("connected_at"),
                "last_verified": blob.get("last_verified"),
                "last_error": blob.get("last_error"),
                "expiry_days": spec.expiry_days,
                "platforms": list(spec.platforms),
                "available": platform_supported(spec.platforms),
                "form_fields": [
                    {"key": f.key, "label": f.label, "secret": f.secret, "placeholder": f.placeholder}
                    for f in spec.form_fields
                ],
                "fetcher_keys": list(spec.fetcher_keys),
            }
        )
    return rows


def mark_invalid(provider: str, *, error: str | None = None) -> None:
    blob = get_provider_blob(provider)
    blob["status"] = "expired"
    blob["last_error"] = error or "Session rejected by provider"
    blob["expired_at"] = _now_iso()
    set_provider_blob(provider, blob)


def mark_connected(provider: str, creds: dict[str, str], *, clear_error: bool = True) -> None:
    blob = get_provider_blob(provider)
    blob.update(creds)
    blob["status"] = "connected"
    blob["connected_at"] = blob.get("connected_at") or _now_iso()
    blob["last_verified"] = _now_iso()
    if clear_error:
        blob.pop("last_error", None)
        blob.pop("expired_at", None)
    set_provider_blob(provider, blob)


def set_form_credentials(provider: str, fields: dict[str, str]) -> dict[str, Any]:
    spec = spec_for(provider)
    if spec.kind not in ("form", "manual") and not spec.form_fields:
        raise ValueError(f"{provider} does not accept saved credentials")
    cleaned = {k: (v or "").strip() for k, v in fields.items() if k in spec.env_keys}
    missing = [k for k in spec.env_keys if not cleaned.get(k)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    if provider == "itch":
        from auth.api_keys import validate_itch_key

        if not validate_itch_key(cleaned["ITCH_API_KEY"]):
            raise ValueError("itch.io rejected this API key — copy a fresh key from your API keys page")
    if provider == "itad":
        from auth.api_keys import validate_itad_key

        if not validate_itad_key(cleaned["ITAD_API_KEY"]):
            raise ValueError(
                "ITAD rejected this API key — copy the API key UUID from isthereanydeal.com/apps/my/"
            )
    if provider == "epic":
        from epic_client import EpicAuthError, EpicClient

        code = cleaned["EPIC_AUTH_CODE"].strip()
        if len(code) < 16 or not re.fullmatch(r"[A-Za-z0-9_\-]+", code):
            raise ValueError(
                "That doesn't look like an Epic authorizationCode. Copy just the "
                "value between the quotes (no quotes, no commas, no spaces)."
            )
        try:
            client = EpicClient(auth_code=code)
            client.login()
        except EpicAuthError as e:
            msg = str(e)
            if "OAuth 400" in msg or "invalid_grant" in msg or "expired" in msg.lower():
                raise ValueError(
                    "That authorizationCode is invalid or already used. Open in browser, "
                    "refresh the page so a new code appears, then paste it here."
                ) from e
            raise ValueError(f"Epic rejected this code: {msg}") from e
    mark_connected(provider, cleaned)
    return {"ok": True, "status": "connected"}


def open_manual_signin(provider: str) -> dict[str, str]:
    """Open the provider settings page in the user's default browser (not Playwright)."""
    import webbrowser

    spec = spec_for(provider)
    if spec.kind != "manual":
        raise ValueError(f"{provider} does not use manual sign-in")
    url = spec.login_url
    if not url:
        raise ValueError(f"{provider} has no sign-in URL configured")
    webbrowser.open(url)
    return {"ok": True, "url": url}


def disconnect(provider: str) -> None:
    delete_provider_blob(provider)
    prof = profile_dir(provider)
    if prof.exists():
        shutil.rmtree(prof, ignore_errors=True)
    if provider == "epic":
        session = epic_cache_dir() / "session.json"
        if session.exists():
            session.unlink(missing_ok=True)


def start_browser_auth(provider: str) -> str:
    spec = spec_for(provider)
    if spec.kind == "manual":
        raise ValueError(f"{provider} uses manual sign-in — click Open in browser and paste your API key")
    if spec.kind not in ("browser", "oauth"):
        raise ValueError(f"{provider} does not support browser sign-in")
    session_id = uuid.uuid4().hex[:12]
    session = AuthSession(session_id, provider)
    with _sessions_lock:
        _active_sessions[session_id] = session

    def _worker() -> None:
        try:
            creds = run_browser_auth(provider, session)
            if creds:
                mark_connected(provider, creds)
                session.emit("extracted", {"status": "connected"})
            else:
                session.emit("error", {"message": "Sign-in cancelled or timed out"})
        except Exception as exc:  # noqa: BLE001
            session.emit("error", {"message": str(exc)})
        finally:
            session.finish()

    threading.Thread(target=_worker, daemon=True, name=f"auth-{provider}").start()
    return session_id


def get_auth_session(session_id: str) -> AuthSession | None:
    with _sessions_lock:
        return _active_sessions.get(session_id)


def subscribe_auth_events(session_id: str, callback: Callable[[str, dict], None]) -> AuthSession | None:
    session = get_auth_session(session_id)
    if session:
        session.add_listener(callback)
    return session


def set_master_password(password: str | None) -> None:
    from auth.secrets import set_master_password_override

    set_master_password_override(password)
