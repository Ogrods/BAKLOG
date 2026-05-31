"""Encrypted credential blob backed by OS keyring (or optional master password)."""

from __future__ import annotations

import json
import os
import secrets
import threading
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from hashlib import scrypt
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
AUTH_DIR = ROOT / "cache" / "auth"
SECRETS_FILE = AUTH_DIR / "secrets.bin"
MASTER_KEY_FILE = AUTH_DIR / ".master_key"
SERVICE_NAME = "steam-backlog"
KEYRING_ACCOUNT = "secrets-master"

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_master_password: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)


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
        MASTER_KEY_FILE.write_bytes(key)


def _get_master_key() -> bytes:
    if _master_password:
        salt_path = AUTH_DIR / ".mpw.salt"
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
    if MASTER_KEY_FILE.exists():
        return MASTER_KEY_FILE.read_bytes()

    key = secrets.token_bytes(32)
    try:
        _save_keyring_key(key)
    except Exception:
        MASTER_KEY_FILE.write_bytes(key)
    return key


def _empty_doc() -> dict[str, Any]:
    return {"providers": {}, "settings": {"master_password_enabled": False}}


def _decrypt_blob(raw: bytes) -> dict[str, Any]:
    if len(raw) < 28:
        return _empty_doc()
    nonce, ciphertext = raw[:12], raw[12:]
    key = _get_master_key()
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    doc = json.loads(plaintext.decode("utf-8"))
    if not isinstance(doc, dict):
        return _empty_doc()
    doc.setdefault("providers", {})
    doc.setdefault("settings", {})
    return doc


def _encrypt_doc(doc: dict[str, Any]) -> bytes:
    key = _get_master_key()
    nonce = os.urandom(12)
    plaintext = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def load_doc() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return json.loads(json.dumps(_cache))
        if not SECRETS_FILE.exists():
            _cache = _empty_doc()
            return json.loads(json.dumps(_cache))
        try:
            _cache = _decrypt_blob(SECRETS_FILE.read_bytes())
        except Exception:
            _cache = _empty_doc()
        return json.loads(json.dumps(_cache))


def save_doc(doc: dict[str, Any]) -> None:
    global _cache
    with _lock:
        _ensure_dir()
        SECRETS_FILE.write_bytes(_encrypt_doc(doc))
        _cache = json.loads(json.dumps(doc))


def get_provider_blob(provider: str) -> dict[str, Any]:
    doc = load_doc()
    blob = doc["providers"].get(provider)
    return dict(blob) if isinstance(blob, dict) else {}


def set_provider_blob(provider: str, blob: dict[str, Any]) -> None:
    doc = load_doc()
    doc["providers"][provider] = blob
    save_doc(doc)


def delete_provider_blob(provider: str) -> None:
    doc = load_doc()
    doc["providers"].pop(provider, None)
    save_doc(doc)


def profile_dir(provider: str) -> Path:
    path = AUTH_DIR / "profiles" / provider
    path.mkdir(parents=True, exist_ok=True)
    return path
