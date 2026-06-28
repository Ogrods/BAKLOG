import json
import os
import secrets
import sys
import threading
from base64 import b64decode, b64encode
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from shared.profile_paths import auth_dir, get_active_profile_id

ROOT = Path(__file__).resolve().parents[1]


def _auth_dir():
    patched = globals().get("AUTH_DIR")
    if isinstance(patched, Path):
        return patched
    return auth_dir()


def _secrets_file():
    patched = globals().get("SECRETS_FILE")
    if isinstance(patched, Path):
        return patched
    return _auth_dir() / "secrets.bin"


def _master_key_file():
    patched = globals().get("MASTER_KEY_FILE")
    if isinstance(patched, Path):
        return patched
    return _auth_dir() / ".master_key"


AUTH_DIR = None
SECRETS_FILE = None
MASTER_KEY_FILE = None
PROFILE_ID_OVERRIDE = None
SERVICE_NAME = "steam-backlog"
KEYRING_ACCOUNT = "secrets-master"
KEY_VERSION_LEGACY = 0
KEY_VERSION_PROFILE = 1
MPW_SCRYPT_N_LOG = 17
MPW_SCRYPT_R = 8
MPW_SCRYPT_P = 1
MPW_LEGACY_N_LOG = 14
_MPW_SALT_MAGIC = b"BKMPW1\n"
_lock = threading.RLock()
_cache = None
_master_password = None
_warned_plaintext_master_key = False
_mpw_kdf_stale = False


def _warn_plaintext_master_key(*, action):
    global _warned_plaintext_master_key
    if _warned_plaintext_master_key:
        return
    _warned_plaintext_master_key = True
    path = _master_key_file()
    print(
        f"[auth] WARNING: OS keyring unavailable — {action} encryption key in plaintext at {path}. Prefer system keyring or set a master password.",
        file=sys.stderr,
    )


def _now_iso():
    return datetime.now(UTC).isoformat()


def _ensure_dir():
    _auth_dir().mkdir(parents=True, exist_ok=True)


def set_master_password_override(password):
    global _master_password, _cache
    with _lock:
        _master_password = (password or "").strip() or None
        _cache = None


def _derive_key_from_password(password, salt, *, n_log=MPW_SCRYPT_N_LOG, r=MPW_SCRYPT_R, p=MPW_SCRYPT_P):
    maxmem = 128 * 2**n_log * r + (1 << 20)
    return scrypt(password.encode("utf-8"), salt=salt, n=2**n_log, r=r, p=p, dklen=32, maxmem=maxmem)


def _read_mpw_kdf():
    salt_path = _auth_dir() / ".mpw.salt"
    _ensure_dir()
    if salt_path.exists():
        raw = salt_path.read_bytes()
        if raw.startswith(_MPW_SALT_MAGIC):
            n_log = raw[len(_MPW_SALT_MAGIC)]
            salt = raw[len(_MPW_SALT_MAGIC) + 1 : len(_MPW_SALT_MAGIC) + 1 + 16]
            return (n_log, salt)
        return (MPW_LEGACY_N_LOG, raw[:16])
    salt = os.urandom(16)
    _write_mpw_kdf(MPW_SCRYPT_N_LOG, salt)
    return (MPW_SCRYPT_N_LOG, salt)


def _write_mpw_kdf(n_log, salt):
    salt_path = _auth_dir() / ".mpw.salt"
    _ensure_dir()
    salt_path.write_bytes(_MPW_SALT_MAGIC + bytes([n_log]) + salt)
    _restrict_file_permissions(salt_path)


def _load_keyring_key():
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


def _save_keyring_key(key):
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


def delete_keyring_master_key():
    try:
        import keyring
        from keyring.errors import KeyringError, PasswordDeleteError
    except ImportError:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, KEYRING_ACCOUNT)
    except PasswordDeleteError:
        return False
    except KeyringError:
        return False
    return True


_DPAPI_MAGIC = b"BAKLOG-DPAPI1\n"


def _dpapi_protect(data):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 1, ctypes.byref(blob_out)):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 1, ctypes.byref(blob_out)):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _restrict_file_permissions(path):
    if os.name == "nt":
        try:
            import subprocess

            user = os.environ.get("USERNAME") or ""
            if not user:
                return
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
            os.chmod(path, 384)
        except OSError:
            pass


def _write_master_key_file(key):
    path = _master_key_file()
    protected = _dpapi_protect(key)
    if protected is not None:
        path.write_bytes(_DPAPI_MAGIC + protected)
    else:
        path.write_bytes(key)
    _restrict_file_permissions(path)


def _read_master_key_file():
    raw = _master_key_file().read_bytes()
    if raw.startswith(_DPAPI_MAGIC):
        unprotected = _dpapi_unprotect(raw[len(_DPAPI_MAGIC) :])
        if unprotected is None:
            raise SecretsCorruptError("DPAPI-protected master key cannot be decrypted (wrong user/machine?)")
        return unprotected
    _warn_plaintext_master_key(action="reading")
    return raw


def _profile_key_from_master(master, profile_id=None):
    pid = (profile_id or _effective_profile_id() or "default").strip() or "default"
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"baklog-profile:" + pid.encode("utf-8")).derive(
        master
    )


def _master_key_unlocks_store(master):
    secrets_path = _secrets_file()
    if not secrets_path.is_file():
        return True
    raw = secrets_path.read_bytes()
    pid = _effective_profile_id()
    try:
        if raw[0:1] == bytes([KEY_VERSION_PROFILE]) and len(raw) >= 29:
            nonce, ciphertext = (raw[1:13], raw[13:])
            AESGCM(_profile_key_from_master(master, pid)).decrypt(nonce, ciphertext, None)
            return True
        if len(raw) >= 28:
            nonce, ciphertext = (raw[:12], raw[12:])
            AESGCM(master).decrypt(nonce, ciphertext, None)
            return True
    except Exception:
        return False
    return False


def _get_master_key():
    global _mpw_kdf_stale
    if _master_password:
        n_log, salt = _read_mpw_kdf()
        _mpw_kdf_stale = n_log < MPW_SCRYPT_N_LOG
        return _derive_key_from_password(_master_password, salt, n_log=n_log)
    keyring_key = _load_keyring_key()
    file_key = None
    if _master_key_file().exists():
        try:
            file_key = _read_master_key_file()
        except SecretsCorruptError:
            file_key = None
    if keyring_key and file_key and (keyring_key != file_key):
        keyring_ok = _master_key_unlocks_store(keyring_key)
        file_ok = _master_key_unlocks_store(file_key)
        if file_ok and (not keyring_ok):
            _save_keyring_key(file_key)
            return file_key
        if keyring_ok and (not file_ok):
            _write_master_key_file(keyring_key)
            return keyring_key
        if file_ok:
            return file_key
        if keyring_ok:
            return keyring_key
    if keyring_key:
        return keyring_key
    if file_key is not None:
        return file_key
    _ensure_dir()
    key = secrets.token_bytes(32)
    if not _save_keyring_key(key):
        _warn_plaintext_master_key(action="writing")
        _write_master_key_file(key)
    return key


def _effective_profile_id():
    override = globals().get("PROFILE_ID_OVERRIDE")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return get_active_profile_id() or "default"


def reset_cache():
    global _cache
    with _lock:
        _cache = None


def _get_profile_key(profile_id=None):
    return _profile_key_from_master(_get_master_key(), profile_id)


class SecretsCorruptError(RuntimeError):
    pass


def _empty_doc():
    return {"providers": {}, "settings": {"master_password_enabled": False}}


def _atomic_write_secrets(data):
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


def _decrypt_blob(raw, profile_id=None):
    if len(raw) < 28:
        raise ValueError("secrets blob is too short to be valid")
    if raw[0:1] == bytes([KEY_VERSION_PROFILE]) and len(raw) >= 29:
        try:
            nonce, ciphertext = (raw[1:13], raw[13:])
            key = _get_profile_key(profile_id)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            doc = json.loads(plaintext.decode("utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("secrets payload is not a JSON object")
            doc.setdefault("providers", {})
            doc.setdefault("settings", {})
            return doc
        except InvalidTag:
            pass
    nonce, ciphertext = (raw[:12], raw[12:])
    key = _get_master_key()
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    doc = json.loads(plaintext.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("secrets payload is not a JSON object")
    doc.setdefault("providers", {})
    doc.setdefault("settings", {})
    return doc


def _encrypt_doc(doc, profile_id=None):
    key = _get_profile_key(profile_id)
    nonce = os.urandom(12)
    plaintext = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return bytes([KEY_VERSION_PROFILE]) + nonce + ciphertext


def _maybe_migrate_legacy_blob(raw, doc, profile_id):
    if raw[:1] == bytes([KEY_VERSION_PROFILE]):
        return
    _atomic_write_secrets(_encrypt_doc(doc, profile_id))


def _maybe_upgrade_mpw_kdf(doc):
    global _mpw_kdf_stale
    if not (_master_password and _mpw_kdf_stale):
        return
    _mpw_kdf_stale = False
    _write_mpw_kdf(MPW_SCRYPT_N_LOG, os.urandom(16))
    save_doc(doc)


def load_doc():
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
            raise SecretsCorruptError(f"cannot read {_secrets_file()}: corrupt or wrong passphrase") from exc
        return json.loads(json.dumps(_cache))


def save_doc(doc):
    global _cache
    with _lock:
        _atomic_write_secrets(_encrypt_doc(doc, _effective_profile_id()))
        _cache = json.loads(json.dumps(doc))


def get_provider_blob(provider):
    try:
        doc = load_doc()
    except SecretsCorruptError:
        return {}
    blob = doc["providers"].get(provider)
    return dict(blob) if isinstance(blob, dict) else {}


def secrets_store_corrupt():
    secrets = _secrets_file()
    if not secrets.is_file():
        return False
    try:
        _decrypt_blob(secrets.read_bytes(), _effective_profile_id())
        return False
    except Exception:
        return True


def reset_secrets_store(*, archive=True):
    global _cache
    with _lock:
        _cache = None
        path = _secrets_file()
        if path.is_file():
            if archive:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                archived = path.with_name(f"secrets.bin.corrupt-{stamp}")
                try:
                    path.replace(archived)
                except OSError:
                    path.unlink(missing_ok=True)
            else:
                path.unlink(missing_ok=True)
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.is_file():
            bak.unlink(missing_ok=True)
        _cache = _empty_doc()


def set_provider_blob(provider, blob):
    doc = load_doc()
    doc["providers"][provider] = blob
    save_doc(doc)


def delete_provider_blob(provider):
    doc = load_doc()
    doc["providers"].pop(provider, None)
    save_doc(doc)


def profile_dir(provider):
    path = _auth_dir() / "profiles" / provider
    path.mkdir(parents=True, exist_ok=True)
    return path
