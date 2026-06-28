import hashlib
import sys
from unittest.mock import patch

import pytest

from shared.update_manager import UpdateManager, reset_update_manager_for_tests
from shared.update_release import ReleaseArtifacts


@pytest.fixture(autouse=True)
def _reset_manager():
    reset_update_manager_for_tests()
    yield
    reset_update_manager_for_tests()


def _artifacts(version="0.8.26"):
    return ReleaseArtifacts(
        tag=f"v{version}",
        version=version,
        html_url=f"https://github.com/Ogrods/BAKLOG/releases/tag/v{version}",
        zip_url=f"https://github.com/Ogrods/BAKLOG/releases/download/v{version}/BAKLOG-win64.zip",
        sha256="",
    )


def test_start_download_blocked_when_not_frozen(monkeypatch):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: False)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False)
    payload = mgr.start_download()
    assert payload["ok"] is False
    assert "installed" in payload["error"].lower()


def test_start_download_blocked_when_fetchers_running(monkeypatch):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: True)
    with patch("shared.update_manager.fetch_release_artifacts", return_value=_artifacts()):
        payload = mgr.start_download()
    assert payload["ok"] is False
    assert "fetcher" in payload["error"].lower()


def test_download_worker_marks_ready_after_verify(monkeypatch, tmp_path):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    payload = b"fake-zip-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    artifacts = ReleaseArtifacts(
        tag="v0.8.26",
        version="0.8.26",
        html_url="https://example.com/release",
        zip_url="https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip",
        sha256=digest,
    )

    def fake_fetch(url, dest, *, max_bytes=0, on_progress=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        if on_progress:
            on_progress(len(payload), len(payload))
        return len(payload)

    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path)
    with patch("shared.update_manager.fetch_release_artifacts", return_value=artifacts):
        with patch("shared.update_manager.fetch_url_to_file", side_effect=fake_fetch):
            started = mgr.start_download()
            assert started["ok"] is True
            assert mgr._thread is not None
            mgr._thread.join(timeout=5)
    status = mgr.status_dict()
    assert status["phase"] == "ready"
    assert status["ready"] is True
    assert status["can_apply"] is True


def test_apply_ready_update_launches_helper_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    monkeypatch.setattr("shared.update_manager.frozen_bundle_dir", lambda: tmp_path)
    (tmp_path / "BAKLOG").write_text("x", encoding="utf-8")
    (tmp_path / "apply_update.sh").write_text("#!/bin/bash", encoding="utf-8")
    payload_bytes = b"verified"
    digest = hashlib.sha256(payload_bytes).hexdigest()
    zip_path = tmp_path / "0.8.26" / "package.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload_bytes)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path)
    with mgr._lock:
        mgr._status.phase = "ready"
        mgr._status.ready = True
        mgr._zip_path = zip_path
        mgr._artifacts = ReleaseArtifacts(
            tag="v0.8.26",
            version="0.8.26",
            html_url="https://example.com",
            zip_url="https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-macos.zip",
            sha256=digest,
        )
    popen_calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            popen_calls.append(cmd)

    monkeypatch.setattr("shared.update_manager.launch_apply_subprocess", lambda **kwargs: FakePopen([]))
    result = mgr.apply_ready_update()
    assert result["ok"] is True


def test_apply_ready_update_launches_helper(monkeypatch, tmp_path):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    monkeypatch.setattr("shared.update_manager.frozen_bundle_dir", lambda: tmp_path)
    (tmp_path / "BAKLOG.exe").write_text("x", encoding="utf-8")
    (tmp_path / "apply_update.ps1").write_text("param([string]$ManifestPath)", encoding="utf-8")
    payload_bytes = b"verified"
    digest = hashlib.sha256(payload_bytes).hexdigest()
    zip_path = tmp_path / "0.8.26" / "package.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload_bytes)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path)
    with mgr._lock:
        mgr._status.phase = "ready"
        mgr._status.ready = True
        mgr._zip_path = zip_path
        mgr._artifacts = ReleaseArtifacts(
            tag="v0.8.26",
            version="0.8.26",
            html_url="https://example.com",
            zip_url="https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip",
            sha256=digest,
        )
    launched = []

    def fake_launch(**kwargs):
        launched.append(True)
        return type("P", (), {})()

    monkeypatch.setattr("shared.update_manager.launch_apply_subprocess", fake_launch)
    result = mgr.apply_ready_update()
    assert result["ok"] is True
    assert launched


def test_apply_rejects_zip_outside_work_root(monkeypatch, tmp_path):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    monkeypatch.setattr("shared.update_manager.frozen_bundle_dir", lambda: tmp_path / "install")
    install = tmp_path / "install"
    install.mkdir()
    (install / "BAKLOG.exe").write_text("x", encoding="utf-8")
    (install / "apply_update.ps1").write_text("param([string]$ManifestPath)", encoding="utf-8")
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"tampered")
    digest = hashlib.sha256(b"tampered").hexdigest()
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path / "work")
    with mgr._lock:
        mgr._status.phase = "ready"
        mgr._status.ready = True
        mgr._zip_path = outside
        mgr._artifacts = ReleaseArtifacts(
            tag="v0.8.26",
            version="0.8.26",
            html_url="https://example.com",
            zip_url="https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip",
            sha256=digest,
        )
    payload = mgr.apply_ready_update()
    assert payload["ok"] is False
    assert "trusted" in payload["error"].lower()


def test_apply_requires_sha256(monkeypatch, tmp_path):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    monkeypatch.setattr("shared.update_manager.frozen_bundle_dir", lambda: tmp_path)
    (tmp_path / "BAKLOG.exe").write_text("x", encoding="utf-8")
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False)
    with mgr._lock:
        mgr._status.phase = "ready"
        mgr._status.ready = True
        mgr._zip_path = tmp_path / "package.zip"
        mgr._zip_path.write_bytes(b"x")
        mgr._artifacts = ReleaseArtifacts(
            tag="v0.8.26",
            version="0.8.26",
            html_url="https://example.com",
            zip_url="https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip",
            sha256="",
        )
    payload = mgr.apply_ready_update()
    assert payload["ok"] is False
    assert "sha256" in payload["error"].lower()


def test_rehydrate_ready_state_on_init(monkeypatch, tmp_path):
    payload = b"verified-package"
    digest = hashlib.sha256(payload).hexdigest()
    version_dir = tmp_path / "0.8.27"
    version_dir.mkdir()
    zip_path = version_dir / "package.zip"
    zip_path.write_bytes(payload)
    from shared.update_ready_state import write_ready_state

    write_ready_state(tmp_path, version="0.8.27", sha256=digest, zip_path=zip_path)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path)
    status = mgr.status_dict()
    assert status["phase"] == "ready"
    assert status["can_apply"] is True
    assert status["version"] == "0.8.27"


def test_discard_ready_update_clears_disk(monkeypatch, tmp_path):
    payload = b"verified-package"
    digest = hashlib.sha256(payload).hexdigest()
    version_dir = tmp_path / "0.8.27"
    version_dir.mkdir()
    zip_path = version_dir / "package.zip"
    zip_path.write_bytes(payload)
    from shared.update_ready_state import write_ready_state

    write_ready_state(tmp_path, version="0.8.27", sha256=digest, zip_path=zip_path)
    mgr = UpdateManager(current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, work_root=tmp_path)
    result = mgr.discard_ready_update()
    assert result["ok"] is True
    assert result["discarded"] is True
    status = mgr.status_dict()
    assert status["phase"] == "idle"
    assert not zip_path.is_file()


def test_start_download_blocked_when_sign_in_active(monkeypatch):
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shared.update_manager.is_running_from_temp_dir", lambda _p: False)
    mgr = UpdateManager(
        current_version=lambda: "0.8.25", has_in_flight_runs=lambda: False, has_active_sessions=lambda: True
    )
    with patch("shared.update_manager.fetch_release_artifacts", return_value=_artifacts()):
        payload = mgr.start_download()
    assert payload["ok"] is False
    assert "sign-in" in payload["error"].lower()
