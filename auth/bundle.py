"""Portable passphrase-encrypted bundle for credentials + CDP browser profiles."""

from __future__ import annotations

import base64
import gzip
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.secrets import _auth_dir, _secrets_file, load_doc, profile_dir, save_doc
from shared.install_paths import bundle_root


def _profiles_root() -> Path:
    return _auth_dir() / "profiles"


def _is_within(base: Path, candidate: Path) -> bool:
    """True only if candidate resolves to a path inside base (blocks ../ escapes)."""
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False

MAGIC = b"BAKLOGSB"
BUNDLE_VERSION = 1
INNER_FORMAT = 1
# scrypt cost. Bumped 14 -> 17 (OWASP-recommended N=2**17, r=8, p=1, ~128 MB).
# The header records the params used per bundle (the "version marker"), so a
# bundle exported with the old N=2**14 still decrypts — _decrypt_payload derives
# the key with the header's params, not these constants.
SCRYPT_N_LOG = 17
SCRYPT_R = 8
SCRYPT_P = 1
# Refuse absurd cost factors from a crafted/corrupt header (memory ≈ 128*2^N*r
# bytes) before handing them to scrypt, which would otherwise OOM the process.
SCRYPT_N_LOG_MAX = 18
MIN_PASSPHRASE_LEN = 8
MAX_BUNDLE_BYTES = 100 * 1024 * 1024

_SKIP_PROFILE_SUFFIXES = (
    ".lock",
    ".tmp",
    "-journal",
    "-wal",
    "-shm",
)
_SKIP_PROFILE_NAMES = frozenset(
    {
        "LOCK",
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "lockfile",
    }
)


class BundleError(Exception):
    """Base error for portable bundle operations."""


class BadPassphrase(BundleError):
    """Decryption failed — wrong passphrase or corrupted ciphertext."""


class BadMagic(BundleError):
    """File is not a BAKLOG secrets bundle."""


class UnsupportedVersion(BundleError):
    """Bundle version is newer than this build understands."""


class BundleTooLarge(BundleError):
    """Bundle exceeds the maximum allowed size."""


@dataclass
class ImportSummary:
    providers_imported: list[str] = field(default_factory=list)
    profiles_imported: list[str] = field(default_factory=list)
    bytes_written: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "providers_imported": list(self.providers_imported),
            "profiles_imported": list(self.profiles_imported),
            "bytes_written": self.bytes_written,
            "dry_run": self.dry_run,
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _app_version() -> str:
    try:
        import tomllib

        with (bundle_root() / "pyproject.toml").open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "unknown"


def _validate_passphrase(passphrase: str) -> None:
    if len((passphrase or "").strip()) < MIN_PASSPHRASE_LEN:
        raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")


def _derive_key(
    passphrase: str,
    salt: bytes,
    *,
    n_log: int = SCRYPT_N_LOG,
    r: int = SCRYPT_R,
    p: int = SCRYPT_P,
) -> bytes:
    # scrypt requires maxmem large enough for the chosen cost; the default
    # 32 MiB cap is exceeded at N=2**17, so size it from the params.
    maxmem = 128 * (2**n_log) * r + (1 << 20)
    return scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=2**n_log,
        r=r,
        p=p,
        dklen=32,
        maxmem=maxmem,
    )


def _should_skip_profile_file(path: Path) -> bool:
    name = path.name
    if name in _SKIP_PROFILE_NAMES:
        return True
    if name.startswith("."):
        return True
    return any(name.endswith(suffix) for suffix in _SKIP_PROFILE_SUFFIXES)


def _collect_profiles() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    root = _profiles_root()
    if not root.is_dir():
        return out
    for provider_dir in sorted(root.iterdir()):
        if not provider_dir.is_dir():
            continue
        files: dict[str, str] = {}
        for file_path in provider_dir.rglob("*"):
            if not file_path.is_file() or _should_skip_profile_file(file_path):
                continue
            rel = file_path.relative_to(provider_dir).as_posix()
            try:
                files[rel] = base64.b64encode(file_path.read_bytes()).decode("ascii")
            except OSError:
                continue
        if files:
            out[provider_dir.name] = files
    return out


def _build_inner_payload(*, include_profiles: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "bundle_format": INNER_FORMAT,
        "exported_at": _now_iso(),
        "app_version": _app_version(),
        "secrets_doc": load_doc(),
        "profiles": _collect_profiles() if include_profiles else {},
        "note": "Generated by BAKLOG. Local-only. See PRIVACY.md.",
    }
    return payload


def _encrypt_payload(passphrase: str, inner: dict[str, Any]) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt)
    plaintext = gzip.compress(json.dumps(inner, ensure_ascii=False).encode("utf-8"), compresslevel=6)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    header = (
        MAGIC
        + bytes([BUNDLE_VERSION, SCRYPT_N_LOG, SCRYPT_R, SCRYPT_P])
        + salt
        + nonce
    )
    return header + ciphertext


def _decrypt_payload(blob: bytes, passphrase: str) -> dict[str, Any]:
    if len(blob) > MAX_BUNDLE_BYTES:
        raise BundleTooLarge(f"bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    if len(blob) < len(MAGIC) + 4 + 16 + 12 + 16:
        raise BadMagic("bundle is too short")
    if blob[: len(MAGIC)] != MAGIC:
        raise BadMagic("invalid bundle magic")
    version = blob[len(MAGIC)]
    if version != BUNDLE_VERSION:
        raise UnsupportedVersion(f"unsupported bundle version {version}")
    # Derive with the params this bundle was written with (header is the version
    # marker), so bundles from before the N=2**17 bump still decrypt.
    n_log = blob[len(MAGIC) + 1]
    scrypt_r = blob[len(MAGIC) + 2]
    scrypt_p = blob[len(MAGIC) + 3]
    if not (1 <= n_log <= SCRYPT_N_LOG_MAX) or scrypt_r < 1 or scrypt_p < 1:
        raise UnsupportedVersion(f"unsupported scrypt parameters (n_log={n_log})")
    offset = len(MAGIC) + 4
    salt = blob[offset : offset + 16]
    nonce = blob[offset + 16 : offset + 28]
    ciphertext = blob[offset + 28 :]
    key = _derive_key(passphrase, salt, n_log=n_log, r=scrypt_r, p=scrypt_p)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise BadPassphrase("could not decrypt bundle — wrong passphrase or corrupted file") from exc
    try:
        inner = json.loads(gzip.decompress(plaintext).decode("utf-8"))
    except Exception as exc:
        raise BadPassphrase("decrypted payload is not valid") from exc
    if not isinstance(inner, dict):
        raise BadPassphrase("decrypted payload is not an object")
    return inner


def export_bundle(passphrase: str, *, include_profiles: bool = True) -> bytes:
    """Build a passphrase-encrypted portable bundle."""
    _validate_passphrase(passphrase)
    inner = _build_inner_payload(include_profiles=include_profiles)
    blob = _encrypt_payload(passphrase, inner)
    if len(blob) > MAX_BUNDLE_BYTES:
        raise BundleTooLarge(f"bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    return blob


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _snapshot_profiles_dir() -> Path | None:
    root = _profiles_root()
    if not root.exists() or not any(root.iterdir()):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    dest = _auth_dir() / f"profiles_pre_import_{stamp}"
    shutil.move(str(root), str(dest))
    return dest


def _restore_profiles(profiles: dict[str, Any], *, dry_run: bool) -> tuple[list[str], int]:
    imported: list[str] = []
    bytes_written = 0
    if not isinstance(profiles, dict):
        return imported, bytes_written
    root = _profiles_root()
    for provider, files in profiles.items():
        if not isinstance(provider, str) or not isinstance(files, dict) or not files:
            continue
        # Reject provider names that would escape the profiles root (path traversal).
        if provider in ("", ".", "..") or "/" in provider or "\\" in provider or os.sep in provider:
            continue
        target = profile_dir(provider)
        if not _is_within(root, target):
            continue
        imported.append(provider)
        if dry_run:
            for b64 in files.values():
                if isinstance(b64, str):
                    bytes_written += len(b64) * 3 // 4
            continue
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        for rel, b64 in files.items():
            if not isinstance(rel, str) or not isinstance(b64, str):
                continue
            out_path = target / rel
            # Block ../ traversal inside the archive — keep writes under target.
            if not _is_within(target, out_path):
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(b64.encode("ascii"))
            _atomic_write_bytes(out_path, data)
            bytes_written += len(data)
    return imported, bytes_written


def import_bundle(blob: bytes, passphrase: str, *, dry_run: bool = False) -> ImportSummary:
    """Decrypt and apply a portable bundle."""
    _validate_passphrase(passphrase)
    inner = _decrypt_payload(blob, passphrase)
    if inner.get("bundle_format") != INNER_FORMAT:
        raise UnsupportedVersion("unsupported inner bundle format")

    secrets_doc = inner.get("secrets_doc")
    if not isinstance(secrets_doc, dict):
        raise BadPassphrase("bundle missing secrets_doc")

    providers = sorted(
        k for k, v in (secrets_doc.get("providers") or {}).items() if isinstance(v, dict) and v
    )
    summary = ImportSummary(providers_imported=providers, dry_run=dry_run)

    if dry_run:
        profiles = inner.get("profiles") or {}
        profile_names, profile_bytes = _restore_profiles(profiles, dry_run=True)
        summary.profiles_imported = profile_names
        summary.bytes_written = profile_bytes
        if isinstance(secrets_doc, dict):
            summary.bytes_written += len(json.dumps(secrets_doc).encode("utf-8"))
        return summary

    _snapshot_profiles_dir()
    save_doc(secrets_doc)
    sf = _secrets_file()
    summary.bytes_written += sf.stat().st_size if sf.exists() else 0

    profiles = inner.get("profiles") or {}
    profile_names, profile_bytes = _restore_profiles(profiles, dry_run=False)
    summary.profiles_imported = profile_names
    summary.bytes_written += profile_bytes
    return summary


def bundle_filename() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"baklog-secrets-{stamp}.bundle"


def parse_bundle_header(blob: bytes) -> dict[str, Any]:
    """Lightweight header parse for tests and diagnostics."""
    if len(blob) < len(MAGIC) + 4:
        raise BadMagic("bundle is too short")
    if blob[: len(MAGIC)] != MAGIC:
        raise BadMagic("invalid bundle magic")
    return {
        "magic": blob[: len(MAGIC)].decode("ascii"),
        "version": blob[len(MAGIC)],
        "scrypt_n_log": blob[len(MAGIC) + 1],
        "scrypt_r": blob[len(MAGIC) + 2],
        "scrypt_p": blob[len(MAGIC) + 3],
    }
