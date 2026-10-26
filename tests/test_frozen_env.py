"""Unit tests for PyInstaller LD_LIBRARY_PATH scrubbing."""

from __future__ import annotations

import pytest

from shared.frozen_env import browser_child_env, scrub_pyinstaller_library_path


def test_scrub_pops_ld_library_path_when_no_orig() -> None:
    env = {
        "PATH": "/usr/bin",
        "LD_LIBRARY_PATH": "/opt/BAKLOG/_internal:/usr/lib",
        "DISPLAY": ":0",
    }
    out = scrub_pyinstaller_library_path(env)
    assert "LD_LIBRARY_PATH" not in out
    assert out["DISPLAY"] == ":0"
    assert out["PATH"] == "/usr/bin"


def test_scrub_restores_ld_library_path_orig() -> None:
    env = {
        "LD_LIBRARY_PATH": "/opt/BAKLOG/_internal",
        "LD_LIBRARY_PATH_ORIG": "/usr/lib:/lib",
        "HOME": "/home/user",
    }
    out = scrub_pyinstaller_library_path(env)
    assert out["LD_LIBRARY_PATH"] == "/usr/lib:/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in out
    assert out["HOME"] == "/home/user"


def test_scrub_drops_internal_ld_preload() -> None:
    env = {
        "LD_PRELOAD": "/opt/BAKLOG/_internal/libfoo.so:/usr/lib/libbar.so",
    }
    out = scrub_pyinstaller_library_path(env)
    assert out["LD_PRELOAD"] == "/usr/lib/libbar.so"

    env2 = {"LD_PRELOAD": "/app/_internal/bad.so"}
    out2 = scrub_pyinstaller_library_path(env2)
    assert "LD_PRELOAD" not in out2


def test_browser_child_env_scrubs_os_environ(monkeypatch) -> None:
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("DISPLAY", ":1")
    out = browser_child_env()
    assert "LD_LIBRARY_PATH" not in out
    assert out.get("DISPLAY") == ":1"


@pytest.mark.no_leak_check
def test_open_url_linux_uses_xdg_open_with_scrubbed_env(monkeypatch) -> None:
    import shutil
    import subprocess
    import sys

    from shared import frozen_env

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/app/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    calls: list[dict] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append({"cmd": list(cmd), "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
    )
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    assert frozen_env.open_url_in_system_browser("http://127.0.0.1:8765/")
    assert calls
    assert calls[0]["cmd"] == ["/usr/bin/xdg-open", "http://127.0.0.1:8765/"]
    env = calls[0]["kwargs"].get("env") or {}
    assert "LD_LIBRARY_PATH" not in env
