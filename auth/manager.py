import contextvars
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from auth.registry import PROVIDERS, spec_for
from auth.runner import AuthSession, run_browser_auth
from auth.secrets import SecretsCorruptError, delete_provider_blob, get_provider_blob, profile_dir, set_provider_blob
from shared.platform_support import platform_supported
from shared.profile_paths import DEFAULT_PROFILE_ID, auth_dir, epic_cache_dir, get_active_profile_id

_LEGACY_ENV_ALIASES = {"battlenet": ("BATTLENET_COOKIE",), "nintendo": ("NINTENDO_COOKIE",)}
ROOT = Path(__file__).resolve().parents[1]
_active_sessions = {}
_sessions_lock = threading.Lock()


def _migrate_unified_epic():
    try:
        epic = get_provider_blob("epic")
    except SecretsCorruptError:
        return
    if not epic.get("EPIC_STORE_COOKIE"):
        return
    wl = get_provider_blob("epic_wishlist")
    wl["EPIC_STORE_COOKIE"] = epic["EPIC_STORE_COOKIE"]
    for key in ("status", "connected_at", "last_verified"):
        if epic.get(key) and (not wl.get(key)):
            wl[key] = epic[key]
    set_provider_blob("epic_wishlist", wl)
    epic.pop("EPIC_STORE_COOKIE", None)
    set_provider_blob("epic", epic)


_migrate_unified_epic()


def _now_iso():
    return datetime.now(UTC).isoformat()


def _env_fallback_allowed():
    return get_active_profile_id() == DEFAULT_PROFILE_ID


def _env_fallback(spec_env_keys):
    if not _env_fallback_allowed():
        return {}
    out = {}
    for key in spec_env_keys:
        val = os.getenv(key, "").strip()
        if val:
            out[key] = val
    return out


def _merge_creds(provider):
    spec = spec_for(provider)
    blob = get_provider_blob(provider)
    out = _env_fallback(spec.env_keys)
    for key in spec.env_keys:
        val = blob.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    if provider == "battlenet" and blob.get("BATTLENET_COOKIE"):
        out["BATTLENET_COOKIE"] = blob["BATTLENET_COOKIE"]
    if provider == "nintendo" and blob.get("NINTENDO_COOKIE"):
        out["NINTENDO_COOKIE"] = blob["NINTENDO_COOKIE"]
    return out


def get_credentials(provider):
    return _merge_creds(provider)


def resolve_env(key, *, provider=None, allow_process_env=True):
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


def _credentials_from_profile_store(provider):
    spec = spec_for(provider)
    blob = get_provider_blob(provider)
    out = {}
    for key in spec.env_keys:
        val = blob.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    if provider == "battlenet" and blob.get("BATTLENET_COOKIE"):
        out["BATTLENET_COOKIE"] = str(blob["BATTLENET_COOKIE"]).strip()
    if provider == "nintendo" and blob.get("NINTENDO_COOKIE"):
        out["NINTENDO_COOKIE"] = str(blob["NINTENDO_COOKIE"]).strip()
    return out


def _with_profile_secrets(profile_id):
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
                _secrets.PROFILE_ID_OVERRIDE,
            )
            _secrets.AUTH_DIR = target_dir
            _secrets.SECRETS_FILE = target_dir / "secrets.bin"
            _secrets.MASTER_KEY_FILE = target_dir / ".master_key"
            _secrets._cache = None
            _secrets.PROFILE_ID_OVERRIDE = profile_id
            try:
                yield
            finally:
                (
                    _secrets.AUTH_DIR,
                    _secrets.SECRETS_FILE,
                    _secrets.MASTER_KEY_FILE,
                    _secrets._cache,
                    _secrets.PROFILE_ID_OVERRIDE,
                ) = saved

    return _cm()


def profile_credentials_env(profile_id):
    out = {}
    with _with_profile_secrets(profile_id):
        for provider in PROVIDERS:
            out.update(_credentials_from_profile_store(provider))
    return out


def subprocess_env_for_profile(profile_id):
    env = {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "BAKLOG_PROFILE": profile_id}
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
    from shared.install_paths import bundle_root, data_root

    env["BAKLOG_DATA_DIR"] = str(data_root().resolve())
    root = str(bundle_root().resolve())
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = root if not existing else f"{root}{os.pathsep}{existing}"
    return env


def _local_data_present(provider, blob):
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
            from clients.amazon_client import default_sql_dir

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
            from clients.gog_galaxy_client import GogGalaxyError, default_galaxy_db

            try:
                db_path = default_galaxy_db()
            except GogGalaxyError:
                return False
        return db_path.is_file()
    if provider == "itch_local":
        env_db = ""
        if _env_fallback_allowed():
            env_db = os.getenv("ITCH_BUTLER_DB", "").strip()
        env_db = env_db or (blob.get("ITCH_BUTLER_DB") or "")
        if isinstance(env_db, str) and env_db.strip() and Path(env_db.strip()).is_file():
            db_path = Path(env_db.strip())
        else:
            from clients.itch_local_client import default_butler_db

            db_path = default_butler_db()
        return db_path.is_file()
    return False


def _provider_state(provider):
    blob = get_provider_blob(provider)
    explicit = blob.get("status")
    spec = spec_for(provider)
    if not platform_supported(spec.platforms):
        return "unavailable"
    if spec.kind == "local":
        if blob.get("disabled"):
            return "disconnected"
        if provider == "itch_local" and (not blob.get("enabled")):
            return "disconnected"
        return "connected" if _local_data_present(provider, blob) else "disconnected"
    if explicit == "expired":
        return "expired"
    if explicit == "connected":
        return "connected"
    if spec.kind == "oauth" and provider == "epic":
        session_blob = get_provider_blob("epic_session")
        if session_blob.get("refresh_token"):
            return "connected"
        session_file = epic_cache_dir() / "session.json"
        env_code = os.getenv("EPIC_AUTH_CODE", "").strip() if _env_fallback_allowed() else ""
        if session_file.exists() or env_code:
            return "unverified" if not session_file.exists() else "connected"
        return "disconnected"
    if _env_fallback_allowed() and any((os.getenv(k, "").strip() for k in spec.env_keys)):
        return "unverified"
    return "disconnected"


def get_status():
    rows = []
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


def mark_invalid(provider, *, error=None):
    blob = get_provider_blob(provider)
    blob["status"] = "expired"
    blob["last_error"] = error or "Session rejected by provider"
    blob["expired_at"] = _now_iso()
    set_provider_blob(provider, blob)


def mark_connected(provider, creds, *, clear_error=True):
    blob = get_provider_blob(provider)
    blob.update(creds)
    blob["status"] = "connected"
    blob["connected_at"] = blob.get("connected_at") or _now_iso()
    blob["last_verified"] = _now_iso()
    if clear_error:
        blob.pop("last_error", None)
        blob.pop("expired_at", None)
    set_provider_blob(provider, blob)
    try:
        from auth.connection_probe import clear_probe_strike
        from shared.profile_paths import get_active_profile_id

        clear_probe_strike(get_active_profile_id(), provider)
    except Exception:
        pass


def mark_verified(provider):
    blob = get_provider_blob(provider)
    blob["last_verified"] = _now_iso()
    set_provider_blob(provider, blob)


def has_active_sessions():
    with _sessions_lock:
        active = [
            {"session_id": sid, "provider": s.provider, "finished": s._finished.is_set()}
            for sid, s in _active_sessions.items()
            if not s._finished.is_set()
        ]
        result = bool(active)
    return result


def seed_new_profile_auth_defaults(profile_id):
    auth_dir(profile_id=profile_id).mkdir(parents=True, exist_ok=True)
    with _with_profile_secrets(profile_id):
        for key, spec in PROVIDERS.items():
            if spec.kind != "local":
                continue
            blob = get_provider_blob(key)
            blob["disabled"] = True
            if key == "itch_local":
                blob.pop("enabled", None)
            set_provider_blob(key, blob)


def migrate_existing_itch_local_opt_in():
    import json

    from shared import profile_paths

    notes = []
    try:
        rows = profile_paths.list_profiles()
        profile_ids = [str(p.get("id")) for p in rows if isinstance(p, dict) and p.get("id")]
    except Exception:
        profile_ids = []
    if profile_paths.DEFAULT_PROFILE_ID not in profile_ids:
        profile_ids.append(profile_paths.DEFAULT_PROFILE_ID)
    for pid in dict.fromkeys(profile_ids):
        try:
            catalog = profile_paths.catalog_path("games_itch.json", profile_id=pid)
            if not catalog.is_file():
                continue
            doc = json.loads(catalog.read_text(encoding="utf-8"))
            games = doc.get("games") if isinstance(doc, dict) else None
            if not isinstance(games, list) or not games:
                continue
            with _with_profile_secrets(pid):
                blob = get_provider_blob("itch_local")
                if blob.get("disabled") or "enabled" in blob:
                    continue
                blob["enabled"] = True
                set_provider_blob("itch_local", blob)
            notes.append(f"itch_local opted in for existing profile with itch library: {pid}")
        except Exception as exc:
            notes.append(f"itch_local opt-in migration skipped for {pid!r}: {exc!r}")
    return notes


def import_env_credentials(*, profile_id=DEFAULT_PROFILE_ID):
    import auth.secrets as _secrets

    target_dir = auth_dir(profile_id=profile_id)
    saved = (_secrets.AUTH_DIR, _secrets.SECRETS_FILE, _secrets.MASTER_KEY_FILE, _secrets._cache)
    imported = []
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
                creds = {}
                for key in spec.env_keys:
                    val = os.getenv(key, "").strip()
                    if val:
                        creds[key] = val
                for alias in _LEGACY_ENV_ALIASES.get(provider, ()):
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


def credential_env_key_names():
    names = set()
    for provider, spec in PROVIDERS.items():
        if spec.kind == "local" or not spec.env_keys:
            continue
        names.update(spec.env_keys)
        names.update(_LEGACY_ENV_ALIASES.get(provider, ()))
    return names


def set_form_credentials(provider, fields):
    spec = spec_for(provider)
    if spec.kind not in ("form", "manual") and (not spec.form_fields):
        raise ValueError(f"{provider} does not accept saved credentials")
    cleaned = {k: (v or "").strip() for k, v in fields.items() if k in spec.env_keys}
    missing = [k for k in spec.env_keys if not cleaned.get(k)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    if provider == "itch":
        from auth.api_keys import KEY_UNREACHABLE, KEY_VALID, validate_itch_key

        result = validate_itch_key(cleaned["ITCH_API_KEY"])
        if result == KEY_UNREACHABLE:
            raise ValueError("Couldn't reach itch.io to verify this key — check your connection and try again.")
        if result != KEY_VALID:
            raise ValueError("itch.io rejected this API key — copy a fresh key from your API keys page")
    if provider == "itad":
        from auth.api_keys import KEY_UNREACHABLE, KEY_VALID, validate_itad_key

        result = validate_itad_key(cleaned["ITAD_API_KEY"])
        if result == KEY_UNREACHABLE:
            raise ValueError("Couldn't reach IsThereAnyDeal to verify this key — check your connection and try again.")
        if result != KEY_VALID:
            raise ValueError("ITAD rejected this API key — copy the API key UUID from isthereanydeal.com/apps/my/")
    if provider == "epic":
        from clients.epic_client import EpicAuthError, EpicClient, EpicCorrectiveActionError, default_epic_cache_dir

        code = cleaned["EPIC_AUTH_CODE"].strip()
        if len(code) < 16 or not re.fullmatch("[A-Za-z0-9_\\-]+", code):
            raise ValueError(
                "That doesn't look like an Epic authorizationCode. Copy just the value between the quotes (no quotes, no commas, no spaces)."
            )
        try:
            client = EpicClient(auth_code=code, cache_dir=default_epic_cache_dir())
            client.login()
        except EpicCorrectiveActionError as e:
            raise ValueError(
                "Epic needs you to accept its privacy policy. In the Epic sign-in window, accept the privacy policy / complete the prompt, then refresh the page and paste a fresh authorizationCode here."
            ) from e
        except EpicAuthError as e:
            msg = str(e)
            if "OAuth 400" in msg or "invalid_grant" in msg or "expired" in msg.lower():
                raise ValueError(
                    "That authorizationCode is invalid or already used. Open in browser, refresh the page so a new code appears, then paste it here."
                ) from e
            raise ValueError(f"Epic rejected this code: {msg}") from e
    mark_connected(provider, cleaned)
    return {"ok": True, "status": "connected"}


def open_manual_signin(provider):
    import webbrowser

    spec = spec_for(provider)
    if spec.kind != "manual":
        raise ValueError(f"{provider} does not use manual sign-in")
    url = spec.login_url
    if not url:
        raise ValueError(f"{provider} has no sign-in URL configured")
    webbrowser.open(url)
    return {"ok": True, "url": url}


def is_local_provider_disabled(provider):
    try:
        spec = spec_for(provider)
    except KeyError:
        return False
    if spec.kind != "local":
        return False
    return bool(get_provider_blob(provider).get("disabled"))


def enable_local(provider):
    spec = spec_for(provider)
    if spec.kind != "local":
        raise ValueError(f"{provider} is not a local provider")
    blob = get_provider_blob(provider)
    blob.pop("disabled", None)
    if provider == "itch_local":
        blob["enabled"] = True
    set_provider_blob(provider, blob)


def clear_browser_session(provider):
    prof = profile_dir(provider)
    try:
        from auth.cdp_browser import release_chromium_profile_lock

        release_chromium_profile_lock(prof)
    except Exception:
        pass
    if provider == "ea":
        try:
            from clients.ea_session import ea_connect_snapshot_path

            ea_connect_snapshot_path().unlink(missing_ok=True)
        except Exception:
            pass
    if prof.exists():
        shutil.rmtree(prof, ignore_errors=True)
    if provider == "epic":
        session = epic_cache_dir() / "session.json"
        if session.exists():
            session.unlink(missing_ok=True)
        delete_provider_blob("epic_session")


def disconnect(provider):
    spec = spec_for(provider)
    if spec.kind == "local":
        blob = get_provider_blob(provider)
        blob["disabled"] = True
        if provider == "itch_local":
            blob.pop("enabled", None)
        set_provider_blob(provider, blob)
        return
    if spec.kind in ("browser", "oauth"):
        from auth.cdp_browser import release_chromium_profile_lock

        release_chromium_profile_lock(profile_dir(provider))
    delete_provider_blob(provider)
    clear_browser_session(provider)


PRESERVE_PROFILE_ON_RECONNECT = frozenset({"epic_wishlist"})


def _should_clear_on_reconnect(provider):
    return provider not in PRESERVE_PROFILE_ON_RECONNECT


def _unfinished_session_for(provider):
    with _sessions_lock:
        for session in _active_sessions.values():
            if session.provider == provider and (not session._finished.is_set()):
                return session
    return None


def start_browser_auth(provider, *, fresh=False):
    spec = spec_for(provider)
    if spec.kind == "manual":
        raise ValueError(f"{provider} uses manual sign-in — click Open in browser and paste your API key")
    if spec.kind not in ("browser", "oauth"):
        raise ValueError(f"{provider} does not support browser sign-in")
    existing = _unfinished_session_for(provider)
    if existing is not None:
        raise ValueError(
            f"A sign-in window for {spec.label} is already open. Finish or close it before starting again."
        )
    if fresh and _should_clear_on_reconnect(provider):
        clear_browser_session(provider)
    elif provider in PRESERVE_PROFILE_ON_RECONNECT:
        if _provider_state(provider) == "disconnected":
            clear_browser_session(provider)
    session_id = uuid.uuid4().hex[:12]
    session = AuthSession(session_id, provider, fresh_connect=fresh)
    with _sessions_lock:
        _active_sessions[session_id] = session

    def _worker():
        try:
            creds = run_browser_auth(provider, session)
            if not creds:
                msg = "Sign-in cancelled or timed out before completing."
                mark_invalid(provider, error=msg)
                session.emit("error", {"message": msg})
                return
            from auth.session_probe import ADVISORY_BROWSER_PROBE, probe_browser_session

            if provider in ADVISORY_BROWSER_PROBE:
                mark_connected(provider, creds)
                session.emit("extracted", {"status": "connected"})
                return
            probe_err = probe_browser_session(provider, creds)
            if probe_err:
                mark_invalid(provider, error=probe_err)
                session.emit("error", {"message": probe_err})
            else:
                mark_connected(provider, creds)
                session.emit("extracted", {"status": "connected"})
        except Exception as exc:
            mark_invalid(provider, error=f"Sign-in did not complete: {exc}")
            session.emit("error", {"message": str(exc)})
        finally:
            session.finish()

    ctx = contextvars.copy_context()
    threading.Thread(target=lambda: ctx.run(_worker), daemon=True, name=f"auth-{provider}").start()
    return session_id


def get_auth_session(session_id):
    with _sessions_lock:
        return _active_sessions.get(session_id)


def subscribe_auth_events(session_id, callback):
    session = get_auth_session(session_id)
    if session:
        session.add_listener(callback)
    return session


def set_master_password(password):
    from auth.secrets import set_master_password_override

    set_master_password_override(password)
