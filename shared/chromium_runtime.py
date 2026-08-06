"""Download and cache a pinned Chrome for Testing build for CDP when no system browser exists."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from shared.install_paths import bundle_root, data_root

MARKER_NAME = "BAKLOG-chromium.json"
PIN_NAME = "chromium_cft_pin.json"
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MiB
_ALLOWED_HOST = "storage.googleapis.com"
_ALLOWED_PATH_PREFIX = "/chrome-for-testing-public/"
_USER_AGENT = "BAKLOG-chromium-runtime"

_download_lock = threading.Lock()

ProgressCallback = Callable[[int, int | None], None]


class ChromiumRuntimeError(RuntimeError):
    """Managed Chromium download or install failed."""


def platform_key() -> str:
    """Return CfT platform id: win64 | mac-arm64 | mac-x64 | linux64."""
    if sys.platform == "win32":
        return "win64"
    machine = (platform.machine() or "").lower()
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return "mac-arm64"
        return "mac-x64"
    return "linux64"


def _pin_path() -> Path:
    candidates = (
        Path(__file__).resolve().parent / PIN_NAME,
        bundle_root() / "shared" / PIN_NAME,
    )
    for path in candidates:
        if path.is_file():
            return path
    raise ChromiumRuntimeError(
        f"Missing Chromium pin file ({PIN_NAME}). Reinstall BAKLOG or restore shared/{PIN_NAME}."
    )


def load_pin() -> dict[str, Any]:
    raw = json.loads(_pin_path().read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("version") or not isinstance(raw.get("platforms"), dict):
        raise ChromiumRuntimeError(f"Invalid Chromium pin file: {_pin_path()}")
    return raw


def chromium_cache_root() -> Path:
    return data_root() / "cache" / "chromium"


def managed_chromium_dir(*, version: str | None = None, plat: str | None = None) -> Path:
    pin = load_pin()
    ver = version or str(pin["version"])
    key = plat or platform_key()
    return chromium_cache_root() / ver / key


def _relative_exe(plat: str) -> Path:
    if plat == "win64":
        return Path("chrome-win64") / "chrome.exe"
    if plat == "mac-arm64":
        return (
            Path("chrome-mac-arm64")
            / "Google Chrome for Testing.app"
            / "Contents"
            / "MacOS"
            / "Google Chrome for Testing"
        )
    if plat == "mac-x64":
        return (
            Path("chrome-mac-x64")
            / "Google Chrome for Testing.app"
            / "Contents"
            / "MacOS"
            / "Google Chrome for Testing"
        )
    if plat == "linux64":
        return Path("chrome-linux64") / "chrome"
    raise ChromiumRuntimeError(f"Unsupported Chromium platform: {plat}")


def managed_chromium_exe(*, version: str | None = None, plat: str | None = None) -> Path:
    key = plat or platform_key()
    return managed_chromium_dir(version=version, plat=key) / _relative_exe(key)


def _read_marker(dest_dir: Path) -> dict[str, Any] | None:
    marker = dest_dir / MARKER_NAME
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_managed_chromium() -> Path | None:
    """Return managed Chrome exe if the pinned install is present and valid."""
    try:
        pin = load_pin()
    except ChromiumRuntimeError:
        return None
    plat = platform_key()
    platforms = pin.get("platforms") or {}
    entry = platforms.get(plat)
    if not isinstance(entry, dict):
        return None
    dest = managed_chromium_dir(version=str(pin["version"]), plat=plat)
    exe = managed_chromium_exe(version=str(pin["version"]), plat=plat)
    marker = _read_marker(dest)
    if marker is None:
        return None
    if str(marker.get("version") or "") != str(pin["version"]):
        return None
    if str(marker.get("platform") or "") != plat:
        return None
    if str(marker.get("sha256") or "").lower() != str(entry.get("sha256") or "").lower():
        return None
    if not exe.is_file():
        return None
    return exe


def downloads_disabled() -> bool:
    return os.environ.get("BAKLOG_NO_CHROMIUM_DOWNLOAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def is_allowed_cft_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host != _ALLOWED_HOST:
        return False
    path = parsed.path or ""
    return path.lower().startswith(_ALLOWED_PATH_PREFIX)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _zip_member_is_safe(member_name: str) -> bool:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        return False
    return True


def safe_extract_cft_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract a CfT zip with path-traversal guards."""
    dest_resolved = dest_dir.resolve()
    dest_resolved.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if not _zip_member_is_safe(info.filename):
                raise ChromiumRuntimeError(f"unsafe zip member: {info.filename}")
            target = (dest_resolved / info.filename).resolve()
            if dest_resolved not in target.parents and target != dest_resolved:
                raise ChromiumRuntimeError(f"zip member escapes target dir: {info.filename}")
        archive.extractall(dest_resolved)


def clear_macos_quarantine(app_bundle: Path) -> None:
    """Clear Gatekeeper quarantine on a macOS .app (best-effort)."""
    if sys.platform != "darwin":
        return
    if not app_bundle.exists():
        return
    import subprocess

    try:
        subprocess.run(
            ["xattr", "-cr", str(app_bundle)],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _chmod_exe(exe: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        mode = exe.stat().st_mode
        exe.chmod(mode | 0o111)
    except OSError:
        pass


def _download_to_file(
    url: str,
    dest: Path,
    *,
    on_progress: ProgressCallback | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> int:
    if not is_allowed_cft_url(url):
        raise ChromiumRuntimeError("Chromium download URL is not allowlisted")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    total = 0
    total_hint: int | None = None
    try:
        with urlopen(req, timeout=120) as resp, dest.open("wb") as handle:
            length = resp.headers.get("Content-Length")
            if length:
                try:
                    total_hint = int(length)
                except ValueError:
                    total_hint = None
            if on_progress:
                on_progress(0, total_hint)
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ChromiumRuntimeError("Chromium download exceeds size cap")
                handle.write(chunk)
                if on_progress:
                    on_progress(total, total_hint)
    except ChromiumRuntimeError:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise ChromiumRuntimeError(f"Chromium download failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surface network failures clearly
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise ChromiumRuntimeError(f"Chromium download failed: {exc}") from exc
    return total


def _write_marker(dest_dir: Path, *, version: str, plat: str, sha256: str, url: str) -> None:
    payload = {
        "version": version,
        "platform": plat,
        "sha256": sha256,
        "url": url,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    marker = dest_dir / MARKER_NAME
    tmp = dest_dir / f".{MARKER_NAME}.tmp"
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(marker)


def _prune_old_versions(keep_version: str) -> None:
    root = chromium_cache_root()
    if not root.is_dir():
        return
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in {keep_version, ".tmp"}:
            continue
        try:
            shutil.rmtree(child, ignore_errors=True)
        except OSError:
            pass


def _mac_app_bundle(plat: str, dest_dir: Path) -> Path | None:
    if plat == "mac-arm64":
        return dest_dir / "chrome-mac-arm64" / "Google Chrome for Testing.app"
    if plat == "mac-x64":
        return dest_dir / "chrome-mac-x64" / "Google Chrome for Testing.app"
    return None


def ensure_chromium(*, on_progress: ProgressCallback | None = None) -> Path:
    """Return a usable Chromium exe, downloading the pinned CfT build if needed."""
    existing = find_managed_chromium()
    if existing is not None:
        return existing

    if downloads_disabled():
        raise ChromiumRuntimeError(
            "No Chrome or Edge browser found, and BAKLOG_NO_CHROMIUM_DOWNLOAD is set. "
            "Install Google Chrome or Microsoft Edge, or set BAKLOG_CHROME_PATH, "
            "or unset BAKLOG_NO_CHROMIUM_DOWNLOAD and go online once."
        )

    pin = load_pin()
    plat = platform_key()
    entry = (pin.get("platforms") or {}).get(plat)
    if not isinstance(entry, dict):
        raise ChromiumRuntimeError(f"Chromium pin has no entry for platform {plat}")
    url = str(entry.get("url") or "").strip()
    expected_sha = str(entry.get("sha256") or "").strip().lower()
    if not url or not expected_sha or len(expected_sha) != 64:
        raise ChromiumRuntimeError(f"Chromium pin entry for {plat} is incomplete")
    if not is_allowed_cft_url(url):
        raise ChromiumRuntimeError("Chromium pin URL is not allowlisted")

    version = str(pin["version"])
    final_dir = managed_chromium_dir(version=version, plat=plat)
    final_exe = managed_chromium_exe(version=version, plat=plat)

    with _download_lock:
        existing = find_managed_chromium()
        if existing is not None:
            return existing

        tmp_root = chromium_cache_root() / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f"cft-{plat}-", dir=tmp_root))
        zip_path = work / "chrome.zip"
        extract_dir = work / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            _download_to_file(url, zip_path, on_progress=on_progress)
            actual_sha = _sha256_file(zip_path)
            if actual_sha.lower() != expected_sha:
                raise ChromiumRuntimeError(
                    "Chromium download failed integrity check (SHA-256 mismatch). "
                    "Delete cache/chromium and try again, or install Chrome/Edge."
                )
            safe_extract_cft_zip(zip_path, extract_dir)
            staged_exe = extract_dir / _relative_exe(plat)
            if not staged_exe.is_file():
                raise ChromiumRuntimeError(
                    f"Chromium archive missing expected executable: {_relative_exe(plat)}"
                )
            app = _mac_app_bundle(plat, extract_dir)
            if app is not None:
                clear_macos_quarantine(app)
            _chmod_exe(staged_exe)

            if final_dir.exists():
                shutil.rmtree(final_dir, ignore_errors=True)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            # Move extracted tree into the versioned cache dir.
            extract_dir.replace(final_dir)
            _write_marker(
                final_dir,
                version=version,
                plat=plat,
                sha256=expected_sha,
                url=url,
            )
            if not final_exe.is_file():
                raise ChromiumRuntimeError("Chromium install finished but executable is missing")
            _prune_old_versions(version)
            return final_exe
        except Exception:
            if final_dir.exists() and not final_exe.is_file():
                shutil.rmtree(final_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
