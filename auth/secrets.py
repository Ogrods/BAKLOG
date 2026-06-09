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

# Master-password KDF (scrypt). Bumped 14 -> 17 (OWASP N=2**17, r=8, p=1).
# The cost factor used for a given store is recorded in .mpw.salt so a store
# written with the old N still unlocks; it is transparently re-encrypted with
# the new N on the next successful unlock (see load_doc).
MPW_SCRYPT_N_LOG = 17
MPW_SCRYPT_R = 8
MPW_SCRYPT_P = 1
MPW_LEGACY_N_LOG = 14
# .mpw.salt layout: MPW_SALT_MAGIC + bytes([n_log]) + 16-byte salt. A bare
# 16-byte file is a legacy salt (implies N=2**14).
_MPW_SALT_MAGIC = b"BKMPW1\n"

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_master_password: str | None = None
_warned_plaintext_master_key = False
# Set by _get_master_key (password path) when the on-disk store used an older
# scrypt cost than MPW_SCRYPT_N_LOG; load_doc re-encrypts once after a
# successful unlock and clears it.
_mpw_kdf_stale = False


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


def _derive_key_from_password(
    password: str,
    salt: bytes,
    *,
    n_log: int = MPW_SCRYPT_N_LOG,
    r: int = MPW_SCRYPT_R,
    p: int = MPW_SCRYPT_P,
) -> bytes:
    # scrypt's default 32 MiB maxmem is exceeded at N=2**17; size it to params.
    maxmem = 128 * (2**n_log) * r + (1 << 20)
    return scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**n_log,
        r=r,
        p=p,
        dklen=32,
        maxmem=maxmem,
    )


def _read_mpw_kdf() -> tuple[int, bytes]:
    """Return (n_log, salt) for the master-password KDF, creating it if absent.

    A fresh salt is written with the current cost. A legacy bare-16-byte salt
    file is reported as N=2**14 so its store still unlocks before upgrade.
    """
    salt_path = _auth_dir() / ".mpw.salt"
    _ensure_dir()
    if salt_path.exists():
        raw = salt_path.read_bytes()
        if raw.startswith(_MPW_SALT_MAGIC):
            n_log = raw[len(_MPW_SALT_MAGIC)]
            salt = raw[len(_MPW_SALT_MAGIC) + 1 : len(_MPW_SALT_MAGIC) + 1 + 16]
            return n_log, salt
        # Legacy: the file is the raw salt (pre-versioning) — old cost factor.
        return MPW_LEGACY_N_LOG, raw[:16]
    salt = os.urandom(16)
    _write_mpw_kdf(MPW_SCRYPT_N_LOG, salt)
    return MPW_SCRYPT_N_LOG, salt


def _write_mpw_kdf(n_log: int, salt: bytes) -> None:
    salt_path = _auth_dir() / ".mpw.salt"
    _ensure_dir()
    salt_path.write_bytes(_MPW_SALT_MAGIC + bytes([n_log]) + salt)
    _restrict_file_permissions(salt_path)


def _load_keyring_key() -> bytes | None:
    # Import errors (keyring not installed) are distinct from runtime keyring
    # failures (no backend / locked store); narrow each so we never swallow an
    # unrelated bug as "keyring unavailable".
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        stored = keyring.get_password(SERVICE_NAME, KEYRING_ACCOUNT)
    except KeyringError:
        return None
    if stored:
        return b64decode(stored.encode("ascii"))
    return None


def _save_keyring_key(key: bytes) -> bool:
    """Store the master key in the OS keyring. Return True on success."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return False
    try:
        keyring.set_password(SERVICE_NAME, KEYRING_ACCOUNT, b64encode(key).decode("ascii"))
    except KeyringError:
        return False
    return True


# Marker prefix for a DPAPI-protected master key on disk (Windows). A file
# without this prefix is a legacy plaintext key written before DPAPI support.
_DPAPI_MAGIC = b"BAKLOG-DPAPI1\n"


def _dpapi_protect(data: bytes) -> bytes | None:
    """Encrypt ``data`` with Windows DPAPI (current-user scope). None elsewhere."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN (0x1): never prompt; fail instead.
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> bytes | None:
    """Decrypt DPAPI-protected ``data``. None when DPAPI is unavailable/fails."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _restrict_file_permissions(path: Path) -> None:
    """Lock a secret file down to the current user (0o600 / owner-only ACL)."""
    if os.name == "nt":
        try:
            import subprocess

            user = os.environ.get("USERNAME") or ""
            if not user:
                return
            # Strip inheritance, then grant the current user full control only.
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _write_master_key_file(key: bytes) -> None:
    """Persist the master key on disk, DPAPI-protected on Windows when possible."""
    path = _master_key_file()
    protected = _dpapi_protect(key)
    if protected is not None:
        path.write_bytes(_DPAPI_MAGIC + protected)
    else:
        path.write_bytes(key)
    _restrict_file_permissions(path)


def _read_master_key_file() -> bytes:
    """Read the on-disk master key, unwrapping DPAPI protection when present."""
    raw = _master_key_file().read_bytes()
    if raw.startswith(_DPAPI_MAGIC):
        unprotected = _dpapi_unprotect(raw[len(_DPAPI_MAGIC):])
        if unprotected is None:
            raise SecretsCorruptError(
                "DPAPI-protected master key cannot be decrypted (wrong user/machine?)"
            )
        return unprotected
    # Legacy plaintext key (pre-DPAPI). Warn so the user can rotate.
    _warn_plaintext_master_key(action="reading")
    return raw


def _get_master_key() -> bytes:
    global _mpw_kdf_stale
    if _master_password:
        n_log, salt = _read_mpw_kdf()
        # Flag (don't act here): a store written with an older cost factor is
        # re-encrypted by load_doc after it confirms the password is correct.
        _mpw_kdf_stale = n_log < MPW_SCRYPT_N_LOG
        return _derive_key_from_password(_master_password, salt, n_log=n_log)

    key = _load_keyring_key()
    if key:
        return key

    _ensure_dir()
    if _master_key_file().exists():
        return _read_master_key_file()

    key = secrets.token_bytes(32)
    if not _save_keyring_key(key):
        _warn_plaintext_master_key(action="writing")
        _write_master_key_file(key)
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
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
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


def _maybe_upgrade_mpw_kdf(doc: dict[str, Any]) -> None:
    """Re-encrypt under the current scrypt cost when the store used an older one.

    Only runs on the master-password path after a successful decrypt (so we
    know the passphrase is right). Rotates to a fresh salt at MPW_SCRYPT_N_LOG,
    then re-encrypts; ``save_doc`` re-derives the key from the just-written salt.
    """
    global _mpw_kdf_stale
    if not (_master_password and _mpw_kdf_stale):
        return
    _mpw_kdf_stale = False
    _write_mpw_kdf(MPW_SCRYPT_N_LOG, os.urandom(16))
    save_doc(doc)


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
            _maybe_upgrade_mpw_kdf(_cache)
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
