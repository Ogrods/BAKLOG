"""In-process update download/apply coordinator (frozen Windows/macOS builds)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from shared.install_paths import frozen_bundle_dir, is_frozen, runtime_label
from shared.server_support import is_running_from_temp_dir, update_available
from shared.update_platform import (
    apply_script_name,
    is_in_app_apply_platform,
    launch_apply_subprocess,
    server_binary_name,
)
from shared.update_ready_state import (
    clear_apply_result,
    clear_applying_lock,
    clear_ready_state,
    read_apply_result,
    scan_ready_state,
    write_applying_lock,
    write_ready_state,
)
from shared.update_release import (
    ReleaseArtifacts,
    UpdateSecurityError,
    fetch_release_artifacts,
    fetch_url_to_file,
    verify_file_sha256,
)

_MANIFEST_NAME = "apply-manifest.json"


@dataclass
class UpdateStatus:
    phase: str = "idle"
    progress_bytes: int = 0
    total_bytes: int | None = None
    version: str | None = None
    error: str | None = None
    ready: bool = False
    can_apply: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UpdateManager:
    def __init__(
        self,
        *,
        current_version: Callable[[], str],
        has_in_flight_runs: Callable[[], bool],
        has_active_sessions: Callable[[], bool] | None = None,
        work_root: Path | None = None,
    ) -> None:
        self._current_version = current_version
        self._has_in_flight_runs = has_in_flight_runs
        self._has_active_sessions = has_active_sessions or (lambda: False)
        self._work_root = (work_root or Path(tempfile.gettempdir()) / "BAKLOG-update").resolve()
        self._lock = threading.Lock()
        self._status = UpdateStatus()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._artifacts: ReleaseArtifacts | None = None
        self._zip_path: Path | None = None
        self._rehydrate_from_disk()

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            payload = self._status.to_dict()
        payload["frozen"] = is_frozen()
        payload["runtime_label"] = runtime_label()
        return payload

    def apply_result_dict(self) -> dict[str, Any] | None:
        return read_apply_result(self._work_root)

    def acknowledge_apply_result(self) -> dict[str, Any]:
        """Clear a successful apply-result once the installed version catches up.

        Leaves in-flight / failed results alone so the pre-restart poll and error
        UI can still read them. Returns whether a success was acknowledged.
        """
        result = read_apply_result(self._work_root)
        if not result:
            return {"ok": True, "acknowledged": False, "result": None}
        version = str(result.get("version") or "").strip()
        success = result.get("ok") is True
        current = str(self._current_version() or "").strip()
        # Only consume successful applies once we are already on that version
        # (or newer). During apply the old process still reports the prior version.
        if not success or not version or update_available(current, version):
            return {"ok": True, "acknowledged": False, "result": result}
        clear_ready_state(self._work_root, version)
        with self._lock:
            if self._status.version == version:
                self._zip_path = None
                self._artifacts = None
                self._status = UpdateStatus()
        clear_apply_result(self._work_root)
        return {
            "ok": True,
            "acknowledged": True,
            "success": True,
            "version": version,
            "result": result,
        }

    def _set_status(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._status, key, value)

    def _rehydrate_from_disk(self) -> None:
        meta = scan_ready_state(self._work_root)
        if not meta:
            return
        version = str(meta.get("version") or "").strip()
        sha256 = str(meta.get("sha256") or "").strip().lower()
        zip_path = Path(str(meta.get("zip_path") or ""))
        if not version or not sha256 or not zip_path.is_file():
            return
        # Drop packages that are already installed (or older). Otherwise a
        # successful Install & restart leaves ready.json and the banner returns.
        current = str(self._current_version() or "").strip()
        if current and not update_available(current, version):
            clear_ready_state(self._work_root, version)
            return
        try:
            verify_file_sha256(zip_path, sha256)
        except UpdateSecurityError:
            return
        zip_url = str(meta.get("zip_url") or "") or None
        html_url = str(meta.get("html_url") or "") or None
        size = zip_path.stat().st_size
        with self._lock:
            self._zip_path = zip_path
            self._artifacts = ReleaseArtifacts(
                tag=f"v{version}",
                version=version,
                html_url=html_url or "",
                zip_url=zip_url or "",
                sha256=sha256,
            )
            self._status = UpdateStatus(
                phase="ready",
                progress_bytes=size,
                total_bytes=size,
                version=version,
                error=None,
                ready=True,
                can_apply=True,
            )

    def _preflight_mutating(self) -> str | None:
        if not is_frozen():
            return "Updates apply only to installed BAKLOG builds"
        if not is_in_app_apply_platform():
            return "In-app apply is not supported on this platform"
        if is_running_from_temp_dir(frozen_bundle_dir()):
            return "Move BAKLOG out of a temporary folder before updating"
        if self._has_active_sessions():
            return "Finish or cancel the sign-in window before updating"
        if self._has_in_flight_runs():
            return "Wait for running fetchers to finish before updating"
        return None

    def start_download(self) -> dict[str, Any]:
        blocked = self._preflight_mutating()
        if blocked:
            return {"ok": False, "error": blocked}

        current = self._current_version()
        try:
            artifacts = fetch_release_artifacts()
        except UpdateSecurityError as exc:
            return {"ok": False, "error": str(exc)}

        if not artifacts.zip_url:
            return {"ok": False, "error": "Release download URL unavailable for this platform"}

        if not update_available(current, artifacts.version):
            return {"ok": False, "error": "Already on latest release"}

        with self._lock:
            if self._status.phase == "downloading":
                return {"ok": True, "started": False, "phase": "downloading"}
            if self._status.phase == "ready" and self._status.version == artifacts.version:
                return {"ok": True, "started": False, "phase": "ready"}

        self._cancel.clear()
        self._artifacts = artifacts
        self._set_status(
            phase="downloading",
            progress_bytes=0,
            total_bytes=None,
            version=artifacts.version,
            error=None,
            ready=False,
            can_apply=False,
        )
        self._thread = threading.Thread(
            target=self._download_worker,
            args=(artifacts,),
            name="baklog-update-download",
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "started": True, "phase": "downloading"}

    def cancel_download(self) -> dict[str, Any]:
        self._cancel.set()
        with self._lock:
            if self._status.phase != "downloading":
                return {"ok": True, "cancelled": False}
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._cleanup_partial()
        self._set_status(
            phase="idle",
            progress_bytes=0,
            total_bytes=None,
            error=None,
            ready=False,
            can_apply=False,
        )
        return {"ok": True, "cancelled": True}

    def discard_ready_update(self) -> dict[str, Any]:
        with self._lock:
            version = self._status.version
            phase = self._status.phase
        if phase != "ready":
            return {"ok": True, "discarded": False}
        clear_ready_state(self._work_root, version)
        with self._lock:
            self._zip_path = None
            self._artifacts = None
        self._set_status(
            phase="idle",
            progress_bytes=0,
            total_bytes=None,
            version=None,
            error=None,
            ready=False,
            can_apply=False,
        )
        return {"ok": True, "discarded": True, "version": version}

    def apply_ready_update(self) -> dict[str, Any]:
        blocked = self._preflight_mutating()
        if blocked:
            return {"ok": False, "error": blocked}

        with self._lock:
            if self._status.phase != "ready" or not self._zip_path or not self._artifacts:
                return {"ok": False, "error": "No verified update package is ready"}
            zip_path = self._zip_path
            artifacts = self._artifacts
            sha256 = artifacts.sha256

        if not sha256:
            return {"ok": False, "error": "Release sha256 unavailable — cannot apply safely"}

        try:
            verify_file_sha256(zip_path, sha256)
        except UpdateSecurityError as exc:
            return {"ok": False, "error": str(exc)}

        work_root = self._work_root.resolve()
        zip_resolved = zip_path.resolve()
        if work_root not in zip_resolved.parents and zip_resolved.parent != work_root:
            return {"ok": False, "error": "Update package path is outside the trusted update workspace"}

        install_dir = frozen_bundle_dir()
        script = install_dir / apply_script_name()
        if not script.is_file():
            return {"ok": False, "error": f"{apply_script_name()} missing from install"}

        server_bin = install_dir / server_binary_name()
        if not server_bin.is_file():
            return {"ok": False, "error": "Install dir is not a BAKLOG bundle"}

        manifest = {
            "install_dir": str(install_dir),
            "zip_path": str(zip_path),
            "sha256": sha256,
            "version": artifacts.version,
            "server_pid": os.getpid(),
            "tray_pid": int(os.environ.get("BAKLOG_TRAY_PID", "0") or 0),
        }
        manifest_path = zip_path.parent / _MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        clear_apply_result(self._work_root)
        write_applying_lock(self._work_root, version=artifacts.version)
        self._set_status(phase="applying", can_apply=False, ready=False)

        try:
            launch_apply_subprocess(
                script=script,
                manifest_path=manifest_path,
                install_dir=install_dir,
            )
        except OSError as exc:
            clear_applying_lock(self._work_root)
            self._set_status(phase="ready", ready=True, can_apply=True, error=str(exc))
            return {"ok": False, "error": f"Failed to launch updater: {exc}"}

        return {"ok": True, "applying": True, "version": artifacts.version}

    def _download_worker(self, artifacts: ReleaseArtifacts) -> None:
        version_dir = self._work_root / artifacts.version
        zip_path = version_dir / "package.zip"

        def on_progress(written: int, total: int | None) -> None:
            self._set_status(progress_bytes=written, total_bytes=total)

        try:
            if self._cancel.is_set():
                raise UpdateSecurityError("download cancelled")
            version_dir.mkdir(parents=True, exist_ok=True)
            if zip_path.is_file() and artifacts.sha256:
                try:
                    verify_file_sha256(zip_path, artifacts.sha256)
                    with self._lock:
                        self._zip_path = zip_path
                    write_ready_state(
                        self._work_root,
                        version=artifacts.version,
                        sha256=artifacts.sha256,
                        zip_path=zip_path,
                        zip_url=artifacts.zip_url,
                        html_url=artifacts.html_url,
                    )
                    self._set_status(
                        phase="ready",
                        ready=True,
                        can_apply=True,
                        progress_bytes=zip_path.stat().st_size,
                        total_bytes=zip_path.stat().st_size,
                        error=None,
                    )
                    return
                except UpdateSecurityError:
                    zip_path.unlink(missing_ok=True)

            if not artifacts.zip_url:
                raise UpdateSecurityError("release download url missing")

            written = fetch_url_to_file(artifacts.zip_url, zip_path, on_progress=on_progress)
            if self._cancel.is_set():
                raise UpdateSecurityError("download cancelled")
            if artifacts.sha256:
                verify_file_sha256(zip_path, artifacts.sha256)
            else:
                self._set_status(
                    phase="error",
                    error="Release missing sha256 sidecar — download kept but apply blocked",
                    ready=False,
                    can_apply=False,
                    progress_bytes=written,
                    total_bytes=written,
                )
                with self._lock:
                    self._zip_path = zip_path
                return

            with self._lock:
                self._zip_path = zip_path
            write_ready_state(
                self._work_root,
                version=artifacts.version,
                sha256=artifacts.sha256 or "",
                zip_path=zip_path,
                zip_url=artifacts.zip_url,
                html_url=artifacts.html_url,
            )
            self._set_status(
                phase="ready",
                ready=True,
                can_apply=True,
                progress_bytes=written,
                total_bytes=written,
                error=None,
            )
        except UpdateSecurityError as exc:
            self._cleanup_partial()
            self._set_status(phase="error", error=str(exc), ready=False, can_apply=False)
        except Exception as exc:  # noqa: BLE001
            self._cleanup_partial()
            self._set_status(phase="error", error=str(exc), ready=False, can_apply=False)

    def _cleanup_partial(self) -> None:
        with self._lock:
            path = self._zip_path
            version = self._status.version
            phase = self._status.phase
            self._zip_path = None
        if path and path.is_file() and phase != "ready":
            path.unlink(missing_ok=True)
            if version:
                clear_ready_state(self._work_root, version)


_MANAGER: UpdateManager | None = None


def get_update_manager(
    *,
    current_version: Callable[[], str],
    has_in_flight_runs: Callable[[], bool],
    has_active_sessions: Callable[[], bool] | None = None,
) -> UpdateManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = UpdateManager(
            current_version=current_version,
            has_in_flight_runs=has_in_flight_runs,
            has_active_sessions=has_active_sessions,
        )
    return _MANAGER


def reset_update_manager_for_tests() -> None:
    global _MANAGER
    _MANAGER = None
