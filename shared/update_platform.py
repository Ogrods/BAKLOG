"""Platform-specific in-app update constants and apply launcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PLATFORM_ARTIFACTS: dict[str, tuple[str, str]] = {
    "win32": ("BAKLOG-win64.zip", "BAKLOG-win64.sha256"),
    "darwin": ("BAKLOG-macos.zip", "BAKLOG-macos.sha256"),
    "linux": ("BAKLOG-linux64.zip", "BAKLOG-linux64.sha256"),
}

# Tray is optional on Linux MVP (server + Start BAKLOG.sh only).
_PLATFORM_BUNDLE_FILES: dict[str, tuple[str, ...]] = {
    "win32": ("BAKLOG.exe", "BAKLOG Tray.exe"),
    "darwin": ("BAKLOG", "BAKLOG Tray"),
    "linux": ("BAKLOG",),
}

_PLATFORM_APPLY_SCRIPT: dict[str, str] = {
    "win32": "apply_update.ps1",
    "darwin": "apply_update.sh",
    "linux": "apply_update.sh",
}

_SUPPORTED_APPLY_PLATFORMS = frozenset({"win32", "darwin", "linux"})


def release_platform(platform: str | None = None) -> str:
    """Platform key for GitHub release zip/sha256 names (win32, darwin, or linux).

    Unknown platforms fall back to win32 artifact names (legacy CI callers).
    """
    plat = platform or sys.platform
    if plat in _PLATFORM_ARTIFACTS:
        return plat
    return "win32"


def current_platform() -> str:
    return sys.platform


def is_in_app_apply_platform(platform: str | None = None) -> bool:
    return (platform or sys.platform) in _SUPPORTED_APPLY_PLATFORMS


def stable_zip_name(platform: str | None = None) -> str:
    plat = platform or sys.platform
    if plat not in _PLATFORM_ARTIFACTS:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_ARTIFACTS[plat][0]


def stable_sha256_name(platform: str | None = None) -> str:
    plat = platform or sys.platform
    if plat not in _PLATFORM_ARTIFACTS:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_ARTIFACTS[plat][1]


def allowed_asset_names() -> frozenset[str]:
    names: set[str] = set()
    for zip_name, sha_name in _PLATFORM_ARTIFACTS.values():
        names.add(zip_name)
        names.add(sha_name)
    names.add("BAKLOG-Setup.exe")
    return frozenset(names)


def apply_script_name(platform: str | None = None) -> str:
    plat = platform or sys.platform
    if plat not in _PLATFORM_APPLY_SCRIPT:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_APPLY_SCRIPT[plat]


def required_bundle_files(platform: str | None = None) -> tuple[str, ...]:
    plat = platform or sys.platform
    if plat not in _PLATFORM_BUNDLE_FILES:
        raise ValueError(f"unsupported update platform: {plat}")
    return _PLATFORM_BUNDLE_FILES[plat]


def server_binary_name(platform: str | None = None) -> str:
    return required_bundle_files(platform)[0]


def tray_binary_name(platform: str | None = None) -> str:
    """Tray launcher basename, or empty string when the platform ships without a tray (Linux MVP)."""
    files = required_bundle_files(platform)
    return files[1] if len(files) > 1 else ""


def apply_log_path() -> Path:
    """Shared apply helper log under the trusted update workspace."""
    import tempfile

    return Path(tempfile.gettempdir()) / "BAKLOG-update" / "apply.log"


def launch_apply_subprocess(*, script: Path, manifest_path: Path, install_dir: Path) -> subprocess.Popen:
    """Launch the platform apply helper after server-side security checks.

    On Windows, do **not** use DETACHED_PROCESS: powershell.exe exits immediately
    with rc=0 when started that way (no console host), so the apply never runs.
    CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP keeps the helper alive; the apply
    script must exclude its own PID when killing the tray/server tree.
    stdout/stderr append to apply.log for frozen-build diagnostics.
    """
    platform = sys.platform
    log_path = apply_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    try:
        if platform == "win32":
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ManifestPath",
                str(manifest_path),
            ]
            # DETACHED_PROCESS (0x8) makes powershell exit instantly — never use it.
            flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
            flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            return subprocess.Popen(  # noqa: S603
                cmd,
                cwd=str(install_dir),
                creationflags=flags,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        if platform in ("darwin", "linux"):
            cmd = [
                "/bin/bash",
                str(script),
                str(manifest_path),
            ]
            return subprocess.Popen(  # noqa: S603
                cmd,
                cwd=str(install_dir),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
    except Exception:
        log_file.close()
        raise
    log_file.close()
    raise OSError(f"In-app apply is not supported on {platform}")
