"""Tests for the system tray launcher (tray_app.py).

Kept light: the pystray UI loop is never started here. We exercise the pure
helpers (URL, interpreter resolution, argv shape) and the ServerController
status/lifecycle guards without spawning a real server.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tray_app


class _PopenStub:
    """Minimal subprocess.Popen stand-in for ServerController tests."""

    pid = 4242

    def poll(self):
        return None

    def communicate(self, input=None, timeout=None):
        return (b"", b"")

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_server_url_uses_host_and_port():
    assert tray_app.server_url() == f"http://{tray_app.HOST}:{tray_app.PORT}/"


def test_python_executable_returns_existing_path():
    exe = tray_app.python_executable()
    assert isinstance(exe, str)
    assert exe


def test_python_executable_honors_override(monkeypatch):
    monkeypatch.setenv("BAKLOG_PYTHON", "/custom/python")
    assert tray_app.python_executable() == "/custom/python"


def test_server_argv_includes_server_py_in_dev(monkeypatch):
    monkeypatch.setattr(tray_app, "is_frozen", lambda: False)
    argv = tray_app._server_argv()
    assert argv[-1].endswith("server.py")
    assert len(argv) == 2


def test_server_argv_frozen_is_self(monkeypatch):
    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    argv = tray_app._server_argv()
    assert argv == [sys.executable]


def test_controller_not_running_when_port_closed(monkeypatch):
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: False)
    ctl = tray_app.ServerController()
    assert ctl.is_running() is False


def test_controller_start_noop_when_already_listening(monkeypatch):
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: True)
    ctl = tray_app.ServerController()
    # Already up: start() returns True and never spawns a process.
    assert ctl.start() is True
    assert ctl.proc is None


def test_controller_start_spawns_and_waits(monkeypatch):
    calls: list[list[str]] = []
    port_seq = iter([False, False, True])

    def fake_popen(argv, **kwargs):
        calls.append(argv)
        return _PopenStub()

    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: next(port_seq, True))
    monkeypatch.setattr(tray_app.subprocess, "Popen", fake_popen)
    ctl = tray_app.ServerController()
    assert ctl.start(wait_secs=1.0) is True
    assert len(calls) == 1
    ctl.proc = None


def test_controller_start_fails_when_child_exits_early(monkeypatch):
    class DeadProc(_PopenStub):
        def poll(self):
            return 1

    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: False)
    monkeypatch.setattr(tray_app.subprocess, "Popen", lambda *a, **k: DeadProc())
    ctl = tray_app.ServerController()
    assert ctl.start(wait_secs=0.5) is False
    assert ctl.proc is None


def test_controller_stop_requests_graceful_shutdown(monkeypatch):
    graceful = {"called": False}

    class LiveProc:
        pid = 4242
        _dead = False

        def poll(self):
            return 1 if self._dead else None

        def wait(self, timeout=None):
            self._dead = True
            return 0

        def terminate(self):
            self._dead = True

        def kill(self):
            self._dead = True

    proc = LiveProc()
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: True)
    monkeypatch.setattr(
        tray_app,
        "_request_graceful_shutdown",
        lambda: graceful.__setitem__("called", True) or True,
    )
    ctl = tray_app.ServerController()
    ctl.proc = proc
    ctl.stop()
    assert graceful["called"] is True
    assert ctl.proc is None


def test_controller_restart_blocked_for_foreign_server(monkeypatch):
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: True)
    ctl = tray_app.ServerController()
    assert ctl.restart() is False


def test_controller_restart_stops_and_starts(monkeypatch):
    stopped = {"n": 0}
    port_open = {"v": False}

    class LiveProc:
        pid = 1

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def fake_stop_port():
        port_open["v"] = False

    def fake_start(wait_secs=12.0):
        port_open["v"] = True
        ctl.proc = LiveProc()
        return True

    ctl = tray_app.ServerController()
    ctl.proc = LiveProc()
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: port_open["v"])
    monkeypatch.setattr(ctl, "stop", lambda: stopped.__setitem__("n", stopped["n"] + 1))
    monkeypatch.setattr(ctl, "start", fake_start)
    assert ctl.restart() is True
    assert stopped["n"] == 1


def test_request_graceful_shutdown_true_when_port_closed(monkeypatch):
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: False)
    assert tray_app._request_graceful_shutdown() is True


def test_controller_stop_is_safe_with_no_process():
    ctl = tray_app.ServerController()
    ctl.stop()  # must not raise
    assert ctl.proc is None


def test_run_headless_returns_1_on_start_failure(monkeypatch):
    ctl = tray_app.ServerController()
    monkeypatch.setattr(ctl, "start", lambda wait_secs=12.0: False)
    assert tray_app._run_headless(ctl) == 1


def test_main_exits_when_lock_held(monkeypatch):
    monkeypatch.setattr(tray_app, "acquire_tray_lock", lambda: False)
    assert tray_app.main() == 0


def test_make_icon_image_dimensions():
    pytest.importorskip("PIL")
    img = tray_app.make_icon_image(48)
    assert img.size == (48, 48)
    assert img.mode == "RGBA"


def test_load_icon_image_falls_back_when_asset_missing(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    monkeypatch.setattr(tray_app, "tray_icon_path", lambda: tmp_path / "missing.png")
    img = tray_app.load_icon_image()
    assert img.size == (64, 64)


def test_load_icon_image_prefers_existing_asset(monkeypatch, tmp_path):
    pytest.importorskip("PIL")
    asset = tmp_path / "tray-icon.png"
    tray_app.make_icon_image(128).save(asset)
    monkeypatch.setattr(tray_app, "tray_icon_path", lambda: asset)
    img = tray_app.load_icon_image()
    assert img.size == (128, 128)


def test_port_open_false_for_unused_port(monkeypatch):
    # Bind an ephemeral port we never listen on; create_connection should fail.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((tray_app.HOST, 0))
    free_port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(tray_app, "PORT", free_port)
    assert tray_app._port_open(timeout=0.2) is False


def test_server_watchdog_notifies_on_owned_child_death(monkeypatch):
    notified: list[tuple[str, str]] = []
    monkeypatch.setattr(tray_app, "_tray_notify", lambda icon, t, m: notified.append((t, m)))
    monkeypatch.setattr(tray_app, "_port_open", lambda timeout=0.3: False)

    class DeadProc:
        def poll(self):
            return 1

    ctl = tray_app.ServerController()
    ctl.proc = DeadProc()
    icon = MagicMock()
    tray_app._start_server_watchdog(icon, ctl)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not notified:
        time.sleep(0.05)
    assert notified
    assert notified[0][0] == "BAKLOG server stopped"
