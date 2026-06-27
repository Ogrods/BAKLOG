"""Read-only install source + Windows Add/Remove Programs version visibility."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from shared.install_paths import frozen_bundle_dir, is_frozen, is_portable_frozen

# Must match packaging/baklog.iss AppId (Inno appends _is1 in Uninstall registry key).
INNO_UNINSTALL_REG_SUFFIX = "{A7B3C9D1-E4F2-4A8B-9C0D-1E2F3A4B5C6D}_is1"


def _has_inno_uninstaller(install_dir: Path) -> bool:
    if not install_dir.is_dir():
        return False
    for name in ("unins000.exe", "uninstall.exe"):
        if (install_dir / name).is_file():
            return True
    return any(install_dir.glob("unins*.exe"))


def detect_install_source() -> str:
    """How this build was installed: dev, portable, setup (Inno), or zip."""
    if not is_frozen():
        return "dev"
    if is_portable_frozen():
        return "portable"
    if sys.platform == "win32" and _has_inno_uninstaller(frozen_bundle_dir()):
        return "setup"
    return "zip"


def read_arp_display_version() -> str | None:
    """Windows Add/Remove Programs DisplayVersion for the Inno uninstall entry."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{INNO_UNINSTALL_REG_SUFFIX}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                raw, _ = winreg.QueryValueEx(key, "DisplayVersion")
        except OSError:
            continue
        text = str(raw or "").strip()
        if text:
            return text
    return None


def arp_version_mismatch(current_version: str, arp_version: str | None) -> bool:
    """True when ARP lists a different version than the running build."""
    from shared.server_support import normalize_version_tag

    if not arp_version or not current_version:
        return False
    return normalize_version_tag(arp_version) != normalize_version_tag(current_version)


def install_trust_fields() -> dict[str, Any]:
    """Unsigned-beta trust notes for frozen builds (no code signing yet)."""
    if not is_frozen():
        return {}
    fields: dict[str, Any] = {"unsigned_beta": True}
    if sys.platform == "win32":
        fields["trust_note"] = (
            "Unsigned beta: SmartScreen may warn on first launch — More info, then Run anyway. "
            "In-app zip updates do not refresh Add/Remove Programs; re-run Setup when you want ARP to match."
        )
    elif sys.platform == "darwin":
        fields["trust_note"] = (
            "Unsigned beta: Gatekeeper may block after in-app update — right-click Open once, "
            "or run: xattr -cr /path/to/BAKLOG.app (or the BAKLOG folder) in Terminal."
        )
    else:
        fields["trust_note"] = "Unsigned beta build — verify downloads from GitHub Releases only."
    return fields


def install_visibility_fields(current_version: str) -> dict[str, Any]:
    arp = read_arp_display_version()
    return {
        "install_source": detect_install_source(),
        "arp_version": arp,
        "arp_version_mismatch": arp_version_mismatch(current_version, arp),
        **install_trust_fields(),
    }
