from __future__ import annotations
import hashlib
import json
from pathlib import Path
from shared.update_ready_state import APPLY_RESULT_FILENAME, PACKAGE_NAME, READY_FILENAME, clear_apply_result, clear_ready_state, read_apply_result, scan_ready_state, write_ready_state

def test_write_and_scan_ready_state(tmp_path: Path) -> None:
    version = '0.8.27'
    payload = b'zip-bytes'
    digest = hashlib.sha256(payload).hexdigest()
    version_dir = tmp_path / version
    version_dir.mkdir()
    zip_path = version_dir / PACKAGE_NAME
    zip_path.write_bytes(payload)
    write_ready_state(tmp_path, version=version, sha256=digest, zip_path=zip_path, zip_url='https://example.com/BAKLOG-win64.zip', html_url='https://example.com/release')
    ready_path = version_dir / READY_FILENAME
    assert ready_path.is_file()
    meta = json.loads(ready_path.read_text(encoding='utf-8'))
    assert meta['version'] == version
    assert meta['sha256'] == digest
    scanned = scan_ready_state(tmp_path)
    assert scanned is not None
    assert scanned['version'] == version
    assert scanned['sha256'] == digest

def test_clear_ready_state_removes_version_dir(tmp_path: Path) -> None:
    version = '0.8.27'
    payload = b'x'
    digest = hashlib.sha256(payload).hexdigest()
    version_dir = tmp_path / version
    version_dir.mkdir()
    zip_path = version_dir / PACKAGE_NAME
    zip_path.write_bytes(payload)
    write_ready_state(tmp_path, version=version, sha256=digest, zip_path=zip_path)
    clear_ready_state(tmp_path, version)
    assert not (version_dir / READY_FILENAME).exists()
    assert not (version_dir / PACKAGE_NAME).exists()

def test_read_apply_result(tmp_path: Path) -> None:
    path = tmp_path / APPLY_RESULT_FILENAME
    path.write_text(json.dumps({'ok': False, 'error': 'copy failed', 'restored_from_backup': True}), encoding='utf-8')
    result = read_apply_result(tmp_path)
    assert result is not None
    assert result['ok'] is False
    assert result['restored_from_backup'] is True
    clear_apply_result(tmp_path)
    assert read_apply_result(tmp_path) is None