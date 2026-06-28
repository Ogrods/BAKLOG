from __future__ import annotations
import os
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEEP = 10

def backup_root_for(path: Path) -> Path:
    from shared.profile_paths import games_backup_root, profile_root
    try:
        return games_backup_root()
    except Exception:
        return profile_root() / 'data' / 'games_backups'

def _stamp() -> str:
    now = time.time()
    return time.strftime('%Y%m%d-%H%M%S', time.localtime(now)) + f'-{int(now % 1 * 1000):03d}'

def rotate_backup(path: Path, *, backup_dir: Path | None=None, prefix: str | None=None, keep: int=DEFAULT_KEEP) -> Path | None:
    if not path.exists():
        return None
    prefix = prefix or path.stem
    backup_dir = backup_dir or backup_root_for(path) / prefix
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f'[safe_write] backup dir create failed for {path.name}: {exc!r}', file=sys.stderr)
        return None
    backup_path = backup_dir / f'{prefix}-{_stamp()}.json'
    try:
        backup_path.write_bytes(path.read_bytes())
    except OSError as exc:
        print(f'[safe_write] backup failed for {path.name}: {exc!r}', file=sys.stderr)
        return None
    backups = sorted(backup_dir.glob(f'{prefix}-*.json'))
    if keep > 0:
        for old in backups[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
    return backup_path

def atomic_write_text(path: Path, text: str, *, encoding: str='utf-8') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    try:
        with open(tmp, 'w', encoding=encoding) as fh:
            fh.write(text)
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

def safe_write_text(path: Path, text: str, *, backup_dir: Path | None=None, prefix: str | None=None, keep: int=DEFAULT_KEEP, encoding: str='utf-8') -> Path | None:
    backup_path = rotate_backup(path, backup_dir=backup_dir, prefix=prefix, keep=keep)
    atomic_write_text(path, text, encoding=encoding)
    return backup_path