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


def _split_env_line(line: str) -> str | None:
    """Return the assignment key for a ``KEY=value`` line, else None (blank/comment)."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _strip_credential_lines(text: str, cred_keys: set[str]) -> tuple[str, bool]:
    """Drop ``KEY=value`` lines whose key is a store credential. Returns (text, removed)."""
    kept: list[str] = []
    removed = False
    for line in text.splitlines():
        key = _split_env_line(line)
        if key is not None and key in cred_keys:
            removed = True
            continue
        kept.append(line)
    new_text = "\n".join(kept)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, removed


def _has_meaningful_config(text: str) -> bool:
    """True when any non-credential ``KEY=value`` assignment remains."""
    return any(_split_env_line(line) is not None for line in text.splitlines())


def maybe_import_legacy_env(root: Path) -> tuple[int, str | None]:
    """Migrate root ``.env`` store credentials into the default profile.

    After import, the plaintext credential lines are stripped from ``.env``.
    Operational config (``BAKLOG_*``, ``AMAZON_GAMES_SQL_DIR``, etc.) is preserved
    so a self-hoster's Supabase/admin settings survive the migration; the file is
    deleted only when nothing but credentials (plus comments/blanks) remained.
    Also removes any pre-existing ``.env.imported`` archive (older builds renamed
    instead of deleting). Returns ``(providers_imported, error_message)``; on
    success ``error_message`` is None. Never raises.
    """
    remediate_env_imported_archive(root)
    env_path = root / ".env"
    if not env_path.is_file():
        return 0, None
    try:
        from auth.manager import credential_env_key_names, import_env_credentials
        from shared.profile_paths import DEFAULT_PROFILE_ID

        keys = import_env_credentials(profile_id=DEFAULT_PROFILE_ID)
        try:
            text = env_path.read_text(encoding="utf-8")
            new_text, _removed = _strip_credential_lines(text, credential_env_key_names())
            if _has_meaningful_config(new_text):
                env_path.write_text(new_text, encoding="utf-8")
            else:
                env_path.unlink()
        except OSError as exc:
            return len(keys), f".env import ok but plaintext cleanup failed: {exc}"
        return len(keys), None
    except Exception as exc:  # noqa: BLE001 - migration must never block boot
        return 0, str(exc)
