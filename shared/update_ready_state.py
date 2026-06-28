from __future__ import annotations
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from shared.update_release import UpdateSecurityError, verify_file_sha256
READY_FILENAME = 'ready.json'
APPLY_RESULT_FILENAME = 'apply-result.json'
PACKAGE_NAME = 'package.zip'

def default_work_root() -> Path:
    return (Path(tempfile.gettempdir()) / 'BAKLOG-update').resolve()

def write_ready_state(work_root: Path, *, version: str, sha256: str, zip_path: Path, zip_url: str | None=None, html_url: str | None=None) -> None:
    version_dir = work_root / version
    version_dir.mkdir(parents=True, exist_ok=True)
    payload = {'version': version, 'sha256': sha256, 'zip_path': str(zip_path.resolve()), 'zip_url': zip_url, 'html_url': html_url, 'written_at': datetime.now(UTC).isoformat()}
    (version_dir / READY_FILENAME).write_text(json.dumps(payload, indent=2), encoding='utf-8')

def clear_ready_state(work_root: Path, version: str | None=None) -> None:
    if version:
        version_dir = work_root / version
        if version_dir.is_dir():
            for name in (READY_FILENAME, PACKAGE_NAME, 'apply-manifest.json'):
                (version_dir / name).unlink(missing_ok=True)
            try:
                version_dir.rmdir()
            except OSError:
                pass
        return
    if not work_root.is_dir():
        return
    for child in work_root.iterdir():
        if child.is_dir():
            clear_ready_state(work_root, child.name)

def read_apply_result(work_root: Path | None=None) -> dict[str, Any] | None:
    root = (work_root or default_work_root()).resolve()
    path = root / APPLY_RESULT_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None

def clear_apply_result(work_root: Path | None=None) -> None:
    path = (work_root or default_work_root()) / APPLY_RESULT_FILENAME
    path.unlink(missing_ok=True)

def scan_ready_state(work_root: Path) -> dict[str, Any] | None:
    if not work_root.is_dir():
        return None
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    for version_dir in work_root.iterdir():
        if not version_dir.is_dir():
            continue
        ready_path = version_dir / READY_FILENAME
        zip_path = version_dir / PACKAGE_NAME
        if not ready_path.is_file() or not zip_path.is_file():
            continue
        try:
            meta = json.loads(ready_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        sha256 = str(meta.get('sha256') or '').strip().lower()
        version = str(meta.get('version') or version_dir.name).strip()
        if not sha256 or len(sha256) != 64:
            continue
        try:
            verify_file_sha256(zip_path, sha256)
        except UpdateSecurityError:
            continue
        written_at = str(meta.get('written_at') or '')
        candidates.append((written_at, zip_path, {**meta, 'version': version, 'zip_path': str(zip_path)}))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][2]