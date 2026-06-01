"""Atomic writes + rotated backups for generated JSON files.

A generalization of the data/personal.json pattern in server.py (atomic temp +
os.replace, plus a rolling set of timestamped backups). Every fetcher's output
is expensive to rebuild — a killed-mid-write event or a fetcher returning
garbage can otherwise silently corrupt or wipe hours of enrichment.

Backup layout (default): <repo>/data/games_backups/<prefix>/<prefix>-<stamp>.json

Stamps include milliseconds so two backups in the same wall-clock second
(common in tests, possible in tight retry loops) don't overwrite each other.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = ROOT / "data" / "games_backups"
DEFAULT_KEEP = 10


def _stamp() -> str:
    """YYYYMMDD-HHMMSS-mmm. Millisecond resolution avoids same-second collisions."""
    now = time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int((now % 1) * 1000):03d}"


def rotate_backup(
    path: Path,
    *,
    backup_dir: Path | None = None,
    prefix: str | None = None,
    keep: int = DEFAULT_KEEP,
) -> Path | None:
    """Copy the existing file at ``path`` into a timestamped backup.

    No-op (returns None) when the source file doesn't exist yet. After a
    successful copy, prunes the oldest backups in the directory so only the
    most recent ``keep`` remain.
    """
    if not path.exists():
        return None
    prefix = prefix or path.stem
    backup_dir = backup_dir or (BACKUP_ROOT / prefix)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"[safe_write] backup dir create failed for {path.name}: {exc!r}",
            file=sys.stderr,
        )
        return None
    backup_path = backup_dir / f"{prefix}-{_stamp()}.json"
    try:
        backup_path.write_bytes(path.read_bytes())
    except OSError as exc:
        print(f"[safe_write] backup failed for {path.name}: {exc!r}", file=sys.stderr)
        return None
    backups = sorted(backup_dir.glob(f"{prefix}-*.json"))
    if keep > 0:
        for old in backups[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
    return backup_path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` via tmp file + os.replace.

    Either the new file is fully on disk or the previous file is untouched.
    The temp file is named ``<path>.tmp`` and is cleaned up on failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def safe_write_text(
    path: Path,
    text: str,
    *,
    backup_dir: Path | None = None,
    prefix: str | None = None,
    keep: int = DEFAULT_KEEP,
    encoding: str = "utf-8",
) -> Path | None:
    """rotate_backup() then atomic_write_text(). Returns the backup path (or None)."""
    backup_path = rotate_backup(path, backup_dir=backup_dir, prefix=prefix, keep=keep)
    atomic_write_text(path, text, encoding=encoding)
    return backup_path
