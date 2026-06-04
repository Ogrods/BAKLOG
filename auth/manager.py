"""Credential resolution, status, and browser-auth orchestration."""

from __future__ import annotations

import contextvars
import os
import re
import shutil
import sys
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auth.registry import PROVIDERS, spec_for
from auth.runner import AuthSession, run_browser_auth
from auth.secrets import (
    SecretsCorruptError,
    delete_provider_blob,
    get_provider_blob,
    profile_dir,
    set_provider_blob,
)
from shared.platform_support import platform_supported
from shared.profile_paths import DEFAULT_PROFILE_ID, auth_dir, epic_cache_dir, get_active_profile_id

# Legacy single-key cookie aliases that _merge_creds also honors.
_LEGACY_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "battlenet": ("BATTLENET_COOKIE",),
    "nintendo": ("NINTENDO_COOKIE",),
}

ROOT = Path(__file__).resolve().parents[1]

_active_sessions: dict[str, AuthSession] = {}
_sessions_lock = threading.Lock()


def _migrate_unified_epic() -> None:
    """Split a previously-unified epic blob back into epic + epic_wishlist."""
    try:
        epic = get_provider_blob("epic")
    except SecretsCorruptError:
        return
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
    return datetime.now(UTC).isoformat()


def _env_fallback_allowed() -> bool:
    """Process .env / exported env vars apply only to the default profile."""
    return get_active_profile_id() == DEFAULT_PROFILE_ID


def _env_fallback(spec_env_keys: tuple[str, ...]) -> dict[str, str]:
    if not _env_fallback_allowed():
        return {}
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


def resolve_env(key: str, *, provider: str | None = None, allow_process_env: bool = True) -> str:
    """Resolve a credential env var from the active profile's encrypted store.

    When ``allow_process_env`` is False (chip missing-requirements checks), only
    values stored for the active profile count — not process-wide ``.env``.
    """
    if provider:
        creds = _credentials_from_profile_store(provider)
        if creds.get(key):
            return creds[key]
    for pkey, spec in PROVIDERS.items():
        if key in spec.env_keys:
            creds = _credentials_from_profile_store(pkey)
            if creds.get(key):
                return creds[key]
    if allow_process_env and _env_fallback_allowed():
        return os.getenv(key, "").strip()
    return ""


def _credentials_from_profile_store(provider: str) -> dict[str, str]:
    """Credentials from the encrypted blob only (no process .env fallback)."""
    spec = spec_for(provider)
    blob = get_provider_blob(provider)
    out: dict[str, str] = {}
    for key in spec.env_keys:
        val = blob.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    if provider == "battlenet" and blob.get("BATTLENET_COOKIE"):
        out["BATTLENET_COOKIE"] = str(blob["BATTLENET_COOKIE"]).strip()
    if provider == "nintendo" and blob.get("NINTENDO_COOKIE"):
        out["NINTENDO_COOKIE"] = str(blob["NINTENDO_COOKIE"]).strip()
    return out


def _with_profile_secrets(profile_id: str):
    """Point auth.secrets at one profile's auth dir (thread-safe; no BAKLOG_PROFILE mutation)."""
    from contextlib import contextmanager

    import auth.secrets as _secrets

    target_dir = auth_dir(profile_id=profile_id)

    @contextmanager
    def _cm():
        with _secrets._lock:
            saved = (
                _secrets.AUTH_DIR,
                _secrets.SECRETS_FILE,
                _secrets.MASTER_KEY_FILE,
                _secrets._cache,
            )
            _secrets.AUTH_DIR = target_dir
            _secrets.SECRETS_FILE = target_dir / "secrets.bin"
            _secrets.MASTER_KEY_FILE = target_dir / ".master_key"
            _secrets._cache = None
            try:
                yield
            finally:
                _secrets.AUTH_DIR, _secrets.SECRETS_FILE, _secrets.MASTER_KEY_FILE, _secrets._cache = (
                    saved
                )

    return _cm()


def profile_credentials_env(profile_id: str) -> dict[str, str]:
    """All env keys from encrypted stores for one profile (no process .env)."""
    out: dict[str, str] = {}
    with _with_profile_secrets(profile_id):
        for provider in PROVIDERS:
            out.update(_credentials_from_profile_store(provider))
    return out


def subprocess_env_for_profile(profile_id: str) -> dict[str, str]:
    """Minimal subprocess environment: system paths + profile-scoped credentials only."""
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "BAKLOG_PROFILE": profile_id,
    }
    for k in (
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "COMSPEC",
        "LANG",
        "LC_ALL",
    ):
        v = os.environ.get(k)
        if v:
            env[k] = v
    env.update(profile_credentials_env(profile_id))
    return env


def _local_data_present(provider: str, blob: dict[str, Any]) -> bool:
    """True when the on-disk launcher/app database for a local provider exists."""
    if provider == "amazon":
        env_dir = ""
        if _env_fallback_allowed():
            env_dir = os.getenv("AMAZON_GAMES_SQL_DIR", "").strip()
        env_dir = env_dir or (blob.get("AMAZON_GAMES_SQL_DIR") or "")
        if isinstance(env_dir, str):
            env_dir = env_dir.strip()
        if env_dir:
            sql_dir = Path(env_dir)
        elif sys.platform != "win32":
            return False
        else:
            from amazon_client import default_sql_dir

            sql_dir = default_sql_dir()
        entitlements = sql_dir / "Entitlements.sqlite"
        return entitlements.is_file()

    if provider == "gog_galaxy":
        env_db = ""
        if _env_fallback_allowed():
            env_db = os.getenv("GOG_GALAXY_DB", "").strip()
        env_db = env_db or (blob.get("GOG_GALAXY_DB") or "")
        if isinstance(env_db, str) and env_db.strip() and Path(env_db.strip()).is_file():
            db_path = Path(env_db.strip())
        else:
            from gog_galaxy_client import default_galaxy_db

            db_path = default_galaxy_db()
        return db_path.is_file()

    if provider == "itch_local":
        env_db = ""
        if _env_fallback_allowed():
            env_db = os.getenv("ITCH_BUTLER_DB", "").strip()
        env_db = env_db or (blob.get("ITCH_BUTLER_DB") or "")
        if isinstance(env_db, str) and env_db.strip() and Path(env_db.strip()).is_file():
            db_path = Path(env_db.strip())
        else:
            from itch_local_client import default_butler_db

            db_path = default_butler_db()
        return db_path.is_file()

    return False


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
        if blob.get("disabled"):
            return "disconnected"
        return "connected" if _local_data_present(provider, blob) else "disconnected"

    if explicit == "expired":
        return "expired"
    if explicit == "connected":
        return "connected"

    if spec.kind == "oauth" and provider == "epic":
        session_file = epic_cache_dir() / "session.json"
        env_code = os.getenv("EPIC_AUTH_CODE", "").strip() if _env_fallback_allowed() else ""
        if session_file.exists() or env_code:
            return "unverified" if not session_file.exists() else "connected"
        return "disconnected"

    if _env_fallback_allowed() and any(os.getenv(k, "").strip() for k in spec.env_keys):
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


def import_env_credentials(*, profile_id: str = DEFAULT_PROFILE_ID) -> list[str]:
    """One-time migration: copy legacy ``.env`` creds into a profile's encrypted blob.

    Writes to ``profile_id``'s ``secrets.bin`` regardless of the active profile by
    temporarily pointing the secrets module at that profile's auth dir. Providers
    already explicitly connected/expired are left untouched. Returns the list of
    provider keys that were imported.
    """
    import auth.secrets as _secrets

    target_dir = auth_dir(profile_id=profile_id)
    saved = (_secrets.AUTH_DIR, _secrets.SECRETS_FILE, _secrets.MASTER_KEY_FILE, _secrets._cache)
    imported: list[str] = []
    with _secrets._lock:
        _secrets.AUTH_DIR = target_dir
        _secrets.SECRETS_FILE = target_dir / "secrets.bin"
        _secrets.MASTER_KEY_FILE = target_dir / ".master_key"
        _secrets._cache = None
        try:
            for provider, spec in PROVIDERS.items():
                if spec.kind == "local" or not spec.env_keys:
                    continue
                existing = get_provider_blob(provider).get("status")
                if existing in ("connected", "expired"):
                    continue
                creds: dict[str, str] = {}
                for key in spec.env_keys:
                    val = os.getenv(key, "").strip()
                    if val:
                        creds[key] = val
                for alias in _LEGACY_ENV_ALIASES.get(provider, ()):  # legacy cookie names
                    val = os.getenv(alias, "").strip()
                    if val:
                        creds[alias] = val
                if not creds:
                    continue
                mark_connected(provider, creds)
                imported.append(provider)
        finally:
            _secrets.AUTH_DIR, _secrets.SECRETS_FILE, _secrets.MASTER_KEY_FILE, _secrets._cache = saved
    return imported


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
        from epic_client import EpicAuthError, EpicClient, default_epic_cache_dir

        code = cleaned["EPIC_AUTH_CODE"].strip()
        if len(code) < 16 or not re.fullmatch(r"[A-Za-z0-9_\-]+", code):
            raise ValueError(
                "That doesn't look like an Epic authorizationCode. Copy just the "
                "value between the quotes (no quotes, no commas, no spaces)."
            )
        try:
            client = EpicClient(auth_code=code, cache_dir=default_epic_cache_dir())
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


def is_local_provider_disabled(provider: str) -> bool:
    """True when the user hid a local-only source (e.g. Amazon Games launcher)."""
    try:
        spec = spec_for(provider)
    except KeyError:
        return False
    if spec.kind != "local":
        return False
    return bool(get_provider_blob(provider).get("disabled"))


def enable_local(provider: str) -> None:
    """Re-enable auto-detection for a local provider after Disconnect."""
    spec = spec_for(provider)
    if spec.kind != "local":
        raise ValueError(f"{provider} is not a local provider")
    blob = get_provider_blob(provider)
    blob.pop("disabled", None)
    set_provider_blob(provider, blob)


def disconnect(provider: str) -> None:
    spec = spec_for(provider)
    if spec.kind == "local":
        blob = get_provider_blob(provider)
        blob["disabled"] = True
        set_provider_blob(provider, blob)
        return
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

    ctx = contextvars.copy_context()
    threading.Thread(
        target=lambda: ctx.run(_worker),
        daemon=True,
        name=f"auth-{provider}",
    ).start()
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
