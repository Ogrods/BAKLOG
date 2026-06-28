from __future__ import annotations
import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import patch
import pytest
from shared.update_release import STABLE_SHA256_NAME, STABLE_ZIP_NAME, UpdateSecurityError, build_release_artifacts, fetch_url_to_file, is_allowed_download_url, locate_bundle_root, parse_sha256_sidecar, safe_extract_zip, verify_file_sha256

def test_is_allowed_download_url_accepts_github_release_asset() -> None:
    url = 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip'
    assert is_allowed_download_url(url) is True

def test_is_allowed_download_url_rejects_evil_host() -> None:
    assert is_allowed_download_url('https://evil.example/BAKLOG-win64.zip') is False

def test_is_allowed_download_url_rejects_non_release_path() -> None:
    url = 'https://github.com/Ogrods/BAKLOG/zipball/main'
    assert is_allowed_download_url(url) is False

def test_is_allowed_download_url_rejects_unknown_asset_name() -> None:
    url = 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/evil.exe'
    assert is_allowed_download_url(url) is False

def test_parse_sha256_sidecar() -> None:
    valid = 'a' * 64 + '  BAKLOG-win64.zip'
    assert parse_sha256_sidecar(valid) == 'a' * 64

def test_build_release_artifacts_from_release_json() -> None:
    release = {'tag_name': 'v0.8.26', 'html_url': 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26', 'assets': [{'name': STABLE_ZIP_NAME, 'browser_download_url': 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip'}, {'name': STABLE_SHA256_NAME, 'browser_download_url': 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.sha256'}]}
    with patch('shared.update_release._fetch_text_asset', return_value='a' * 64 + '  BAKLOG-win64.zip'):
        artifacts = build_release_artifacts(release, platform='win32')
    assert artifacts.version == '0.8.26'
    assert artifacts.zip_url.endswith(STABLE_ZIP_NAME)

def test_verify_file_sha256_detects_tamper(tmp_path: Path) -> None:
    target = tmp_path / 'file.bin'
    target.write_bytes(b'hello')
    digest = hashlib.sha256(b'hello').hexdigest()
    verify_file_sha256(target, digest)
    with pytest.raises(UpdateSecurityError):
        verify_file_sha256(target, '0' * 64)

def _write_test_bundle_zip(dest: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('BAKLOG/BAKLOG.exe', b'exe')
        archive.writestr('BAKLOG/BAKLOG Tray.exe', b'tray')
    dest.write_bytes(buf.getvalue())

def test_safe_extract_zip_rejects_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / 'bad.zip'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('../evil.txt', b'nope')
    zip_path.write_bytes(buf.getvalue())
    with pytest.raises(UpdateSecurityError):
        safe_extract_zip(zip_path, tmp_path / 'out')

def test_safe_extract_zip_and_locate_bundle_root(tmp_path: Path) -> None:
    zip_path = tmp_path / 'good.zip'
    _write_test_bundle_zip(zip_path)
    root = safe_extract_zip(zip_path, tmp_path / 'extract')
    assert (root / 'BAKLOG.exe').is_file()
    assert locate_bundle_root(tmp_path / 'extract') == root

def test_fetch_url_to_file_rejects_disallowed_url(tmp_path: Path) -> None:
    with pytest.raises(UpdateSecurityError):
        fetch_url_to_file('https://evil.example/x.zip', tmp_path / 'x.zip')

def test_build_release_artifacts_macos_asset() -> None:
    release = {'tag_name': 'v0.8.26', 'html_url': 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26', 'assets': [{'name': 'BAKLOG-macos.zip', 'browser_download_url': 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-macos.zip'}, {'name': 'BAKLOG-macos.sha256', 'browser_download_url': 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-macos.sha256'}]}
    with patch('shared.update_release._fetch_text_asset', return_value='a' * 64 + '  BAKLOG-macos.zip'):
        artifacts = build_release_artifacts(release, platform='darwin')
    assert artifacts.version == '0.8.26'
    assert artifacts.zip_url is not None
    assert artifacts.zip_url.endswith('BAKLOG-macos.zip')

def test_build_release_artifacts_macos_missing_asset() -> None:
    release = {'tag_name': 'v0.8.26', 'html_url': 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26', 'assets': [{'name': 'BAKLOG-win64.zip', 'browser_download_url': 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip'}]}
    artifacts = build_release_artifacts(release, platform='darwin')
    assert artifacts.zip_url is None