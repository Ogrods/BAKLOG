"""Encrypted credential blob backed by OS keyring (or optional master password)."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from base64 import b64decode, b64encode
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from shared.profile_paths import auth_dir, get_active_profile_id

ROOT = Path(__file__).resolve().parents[1]


def _auth_dir() -> Path:
    patched = globals().get("AUTH_DIR")
    if isinstance(patched, Path):
        return patched
    return auth_dir()


def _secrets_file() -> Path:
    patched = globals().get("SECRETS_FILE")
    if isinstance(patched, Path):
        return patched
    return _auth_dir() / "secrets.bin"


def _master_key_file() -> Path:
    patched = globals().get("MASTER_KEY_FILE")
    if isinstance(patched, Path):
        return patched
    return _auth_dir() / ".master_key"


# Back-compat names for auth.bundle and tests (monkeypatch these Path hooks).
AUTH_DIR: Path | None = None
SECRETS_FILE: Path | None = None
MASTER_KEY_FILE: Path | None = None
# When set (e.g. inside auth.manager._with_profile_secrets), key derivation uses
# this profile id instead of the live active profile. Keeps load/save/key in sync
# with the patched SECRETS_FILE when operating on a non-active profile.
PROFILE_ID_OVERRIDE: str | None = None
SERVICE_NAME = "steam-backlog"
KEYRING_ACCOUNT = "secrets-master"
KEY_VERSION_LEGACY = 0
KEY_VERSION_PROFILE = 1

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_master_password: str | None = None
_warned_plaintext_master_key = False


def _warn_plaintext_master_key(*, action: str) -> None:
    global _warned_plaintext_master_key
    if _warned_plaintext_master_key:
        return
    _warned_plaintext_master_key = True
    path = _master_key_file()
    print(
        f"[auth] WARNING: OS keyring unavailable — {action} encryption key in plaintext "
        f"at {path}. Prefer system keyring or set a master password.",
        file=sys.stderr,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_dir() -> None:
    _auth_dir().mkdir(parents=True, exist_ok=True)


def set_master_password_override(password: str | None) -> None:
    """Optional portable encryption passphrase (Phase 5)."""
    global _master_password, _cache
    with _lock:
        _master_password = (password or "").strip() or None
        _cache = None


def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    return scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def _load_keyring_key() -> bytes | None:
    try:
        import keyring

        stored = keyring.get_password(SERVICE_NAME, KEYRING_ACCOUNT)
        if stored:
            return b64decode(stored.encode("ascii"))
    except Exception:
        pass
    return None


def _save_keyring_key(key: bytes) -> None:
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, KEYRING_ACCOUNT, b64encode(key).decode("ascii"))
    except Exception:
        _warn_plaintext_master_key(action="writing")
        _master_key_file().write_bytes(key)


def _get_master_key() -> bytes:
    if _master_password:
        salt_path = _auth_dir() / ".mpw.salt"
        _ensure_dir()
        if salt_path.exists():
            salt = salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            salt_path.write_bytes(salt)
        return _derive_key_from_password(_master_password, salt)

    key = _load_keyring_key()
    if key:
        return key

    _ensure_dir()
    mk = _master_key_file()
    if mk.exists():
        _warn_plaintext_master_key(action="reading")
        return mk.read_bytes()

    key = secrets.token_bytes(32)
    try:
        _save_keyring_key(key)
    except Exception:
        _warn_plaintext_master_key(action="writing")
        _master_key_file().write_bytes(key)
    return key


def _effective_profile_id() -> str:
    override = globals().get("PROFILE_ID_OVERRIDE")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return get_active_profile_id() or "default"


def reset_cache() -> None:
    """Drop the decrypted secrets cache (call after the active profile changes)."""
    global _cache
    with _lock:
        _cache = None


def _get_profile_key(profile_id: str | None = None) -> bytes:
    pid = (profile_id or _effective_profile_id() or "default").strip() or "default"
    master = _get_master_key()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"baklog-profile:" + pid.encode("utf-8"),
    ).derive(master)


class SecretsCorruptError(RuntimeError):
    """secrets.bin exists but cannot be decrypted or parsed."""


def _empty_doc() -> dict[str, Any]:
    return {"providers": {}, "settings": {"master_password_enabled": False}}


def _atomic_write_secrets(data: bytes) -> None:
    path = _secrets_file()
    _ensure_dir()
    bak = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _decrypt_blob(raw: bytes, profile_id: str | None = None) -> dict[str, Any]:
    if len(raw) < 28:
        raise ValueError("secrets blob is too short to be valid")
    if raw[0:1] == bytes([KEY_VERSION_PROFILE]) and len(raw) >= 29:
        try:
            nonce, ciphertext = raw[1:13], raw[13:]
            key = _get_profile_key(profile_id)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            doc = json.loads(plaintext.decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("secrets payload is not a JSON object")
            doc.setdefault("providers", {})
            doc.setdefault("settings", {})
            return doc
        except InvalidTag:
            # A legacy v0 blob whose random nonce happens to begin with
            # KEY_VERSION_PROFILE collides with the version prefix. Fall through
            # and retry as legacy rather than treating it as corrupt.
            pass

    # Legacy v0: master key directly on nonce || ciphertext.
    nonce, ciphertext = raw[:12], raw[12:]
    key = _get_master_key()
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    doc = json.loads(plaintext.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("secrets payload is not a JSON object")
    doc.setdefault("providers", {})
    doc.setdefault("settings", {})
    return doc


def _encrypt_doc(doc: dict[str, Any], profile_id: str | None = None) -> bytes:
    key = _get_profile_key(profile_id)
    nonce = os.urandom(12)
    plaintext = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return bytes([KEY_VERSION_PROFILE]) + nonce + ciphertext


def _maybe_migrate_legacy_blob(raw: bytes, doc: dict[str, Any], profile_id: str | None) -> None:
    if raw[:1] == bytes([KEY_VERSION_PROFILE]):
        return
    _atomic_write_secrets(_encrypt_doc(doc, profile_id))


def load_doc() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return json.loads(json.dumps(_cache))
        secrets = _secrets_file()
        if not secrets.exists():
            _cache = _empty_doc()
            return json.loads(json.dumps(_cache))
        try:
            raw = secrets.read_bytes()
            pid = _effective_profile_id()
            _cache = _decrypt_blob(raw, pid)
            _maybe_migrate_legacy_blob(raw, _cache, pid)
        except Exception as exc:
            raise SecretsCorruptError(
                f"cannot read {_secrets_file()}: corrupt or wrong passphrase"
            ) from exc
        return json.loads(json.dumps(_cache))


def save_doc(doc: dict[str, Any]) -> None:
    global _cache
    with _lock:
        _atomic_write_secrets(_encrypt_doc(doc, _effective_profile_id()))
        _cache = json.loads(json.dumps(doc))


def get_provider_blob(provider: str) -> dict[str, Any]:
    try:
        doc = load_doc()
    except SecretsCorruptError:
        return {}
    blob = doc["providers"].get(provider)
    return dict(blob) if isinstance(blob, dict) else {}


def secrets_store_corrupt() -> bool:
    """True when secrets.bin exists but cannot be decrypted."""
    secrets = _secrets_file()
    if not secrets.is_file():
        return False
    try:
        _decrypt_blob(secrets.read_bytes(), _effective_profile_id())
        return False
    except Exception:
        return True


def set_provider_blob(provider: str, blob: dict[str, Any]) -> None:
    doc = load_doc()
    doc["providers"][provider] = blob
    save_doc(doc)


def delete_provider_blob(provider: str) -> None:
    doc = load_doc()
    doc["providers"].pop(provider, None)
    save_doc(doc)


def profile_dir(provider: str) -> Path:
    path = _auth_dir() / "profiles" / provider
    path.mkdir(parents=True, exist_ok=True)
    return path
