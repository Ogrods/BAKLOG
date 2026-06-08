"""Tests for the system tray launcher (tray_app.py).

Kept light: the pystray UI loop is never started here. We exercise the pure
helpers (URL, interpreter resolution, argv shape) and the ServerController
status/lifecycle guards without spawning a real server.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tray_app


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


def test_controller_stop_is_safe_with_no_process():
    ctl = tray_app.ServerController()
    ctl.stop()  # must not raise
    assert ctl.proc is None


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
