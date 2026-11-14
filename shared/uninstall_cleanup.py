"""Uninstall helpers: login autostart, keyring, and data dir (all platforms).

``cleanup_autostart`` delegates to ``shared.startup.disable_startup`` which already
covers Windows registry, macOS LaunchAgent, and Linux XDG autostart.
"""

from __future__ import annotations

import os
import shutil
import socket
import time
import urllib.request
from pathlib import Path

from shared.startup import disable_startup

_SHUTDOWN_HOST = "127.0.0.1"
_SHUTDOWN_PORT = int(os.environ.get("PORT", "8765"))

# Portable installs colocate data with the exe. Never rmtree the bundle root;
# only remove these known user-data names (see shared/data_dir_migration.py).
_PORTABLE_WIPE_DIRNAMES = ("profiles", "data", "cache")
_PORTABLE_WIPE_FILENAMES = (".env",)


class WipeIncompleteError(RuntimeError):
    """Data dir wipe failed; keyring master key was intentionally left intact."""


def _request_graceful_shutdown() -> bool:
    """POST /api/shutdown when the local server is up. Best-effort."""
    try:
        with socket.create_connection((_SHUTDOWN_HOST, _SHUTDOWN_PORT), timeout=0.3):
            pass
    except OSError:
        return False
    req = urllib.request.Request(
        f"http://{_SHUTDOWN_HOST}:{_SHUTDOWN_PORT}/api/shutdown",
        method="POST",
        headers={"X-BAKLOG-Local": "1"},
        data=b"",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except OSError:
        return False
    for _ in range(30):
        time.sleep(0.1)
        try:
            with socket.create_connection((_SHUTDOWN_HOST, _SHUTDOWN_PORT), timeout=0.3):
                continue
        except OSError:
            return True
    return False


def cleanup_autostart() -> None:
    """Remove login autostart registration (Windows / macOS / Linux)."""
    disable_startup()


def assert_wipe_target_allowed(data_dir: Path) -> Path:
    """Resolve and validate a wipe target. Raises ValueError if unsafe."""
    from shared.install_paths import (
        default_frozen_data_dir,
        frozen_bundle_dir,
        is_frozen,
        is_portable_frozen,
    )

    resolved = data_dir.expanduser().resolve()
    if is_frozen():
        bundle = frozen_bundle_dir().resolve()
        if resolved == bundle:
            if not is_portable_frozen():
                raise ValueError(
                    f"refusing to wipe install bundle (not portable): {resolved}"
                )
            return resolved
        # Never wipe a parent of the running bundle (would delete the exe).
        try:
            bundle.relative_to(resolved)
        except ValueError:
            pass
        else:
            if resolved != bundle:
                raise ValueError(
                    f"refusing to wipe ancestor of install bundle: {resolved}"
                )
        if (resolved / "_internal").is_dir() and resolved != bundle:
            raise ValueError(f"refusing to wipe a frozen onedir tree: {resolved}")

    # Leaf names for dedicated data roots only — never the Windows install
    # folder name "BAKLOG" (that is the frozen bundle beside Tray.exe).
    allowed_names = {"BAKLOG-Data", "BAKLOG-Dev", "baklog"}
    if resolved.name in allowed_names:
        return resolved
    try:
        if resolved == default_frozen_data_dir().resolve():
            return resolved
    except OSError:
        pass
    raise ValueError(
        f"refusing wipe of unexpected data dir {resolved} "
        f"(expected BAKLOG-Data / portable install / default data root)"
    )


def _rmtree_with_retries(path: Path, *, attempts: int = 3) -> None:
    last_err: OSError | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.4 * (attempt + 1))
    assert last_err is not None
    raise last_err


def _wipe_portable_bundle_data(bundle: Path, notes: list[str]) -> None:
    """Remove colocated user data without deleting Tray.exe / _internal."""
    removed_any = False
    for name in _PORTABLE_WIPE_DIRNAMES:
        target = bundle / name
        if target.is_dir():
            _rmtree_with_retries(target)
            notes.append(f"Removed {target}")
            removed_any = True
    for name in _PORTABLE_WIPE_FILENAMES:
        target = bundle / name
        if target.is_file():
            target.unlink()
            notes.append(f"Removed {target}")
            removed_any = True
    for path in bundle.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if (name.startswith("games_") or name.startswith("games_wishlist_")) and name.endswith(
            ".json"
        ):
            path.unlink()
            notes.append(f"Removed {path}")
            removed_any = True
    if not removed_any:
        notes.append(f"No portable data entries found under {bundle}")


def wipe_user_data(data_dir: Path) -> list[str]:
    """Remove library data dir, then OS keyring master key.

    Keyring is deleted only after the data wipe succeeds so a failed ``rmtree``
    cannot leave an undecryptable ``secrets.bin`` behind.
    """
    from shared.install_paths import frozen_bundle_dir, is_frozen, is_portable_frozen
    from auth.secrets import delete_keyring_master_key

    notes: list[str] = []
    _request_graceful_shutdown()
    cleanup_autostart()

    try:
        resolved = assert_wipe_target_allowed(data_dir)
    except ValueError as exc:
        notes.append(f"FAILED wipe: {exc}")
        raise WipeIncompleteError(str(exc)) from exc

    try:
        if (
            is_frozen()
            and is_portable_frozen()
            and resolved == frozen_bundle_dir().resolve()
        ):
            _wipe_portable_bundle_data(resolved, notes)
        elif resolved.is_dir():
            _rmtree_with_retries(resolved)
            if resolved.exists():
                raise WipeIncompleteError(f"wipe incomplete: {resolved} still exists")
            notes.append(f"Removed {resolved}")
        else:
            notes.append(f"No data dir at {resolved}")
    except WipeIncompleteError:
        raise
    except OSError as exc:
        notes.append(f"FAILED removing {resolved}: {exc}")
        raise WipeIncompleteError(f"wipe incomplete: {resolved}: {exc}") from exc

    if delete_keyring_master_key():
        notes.append("Removed OS keyring master key")
    return notes
