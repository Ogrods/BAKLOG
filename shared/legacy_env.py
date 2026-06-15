"""One-time legacy .env credential migration into encrypted profile storage."""

from __future__ import annotations

from pathlib import Path


def remediate_env_imported_archive(root: Path) -> bool:
    """Delete a leftover ``.env.imported`` plaintext archive from older builds.

    Returns True when a file was removed. Never raises.
    """
    imported_path = root / ".env.imported"
    if not imported_path.is_file():
        return False
    try:
        imported_path.unlink()
        return True
    except OSError:
        return False


def maybe_import_legacy_env(root: Path) -> tuple[int, str | None]:
    """Migrate root ``.env`` credentials into the default profile, then delete ``.env``.

    Also removes any pre-existing ``.env.imported`` archive (older builds renamed
    instead of deleting). Returns ``(providers_imported, error_message)``; on
    success ``error_message`` is None. Never raises.
    """
    remediate_env_imported_archive(root)
    env_path = root / ".env"
    if not env_path.is_file():
        return 0, None
    try:
        from auth.manager import import_env_credentials
        from shared.profile_paths import DEFAULT_PROFILE_ID

        keys = import_env_credentials(profile_id=DEFAULT_PROFILE_ID)
        try:
            env_path.unlink()
        except OSError as exc:
            return len(keys), f".env import ok but delete failed: {exc}"
        return len(keys), None
    except Exception as exc:  # noqa: BLE001 - migration must never block boot
        return 0, str(exc)
