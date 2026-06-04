"""Tests for server._python_executable resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

import server


def test_python_executable_baklog_python_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake = tmp_path / "custom-python.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("BAKLOG_PYTHON", str(fake))
    assert server._python_executable() == str(fake)


def test_python_executable_prefers_venv_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("BAKLOG_PYTHON", raising=False)
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    assert server._python_executable() == str(venv_py)
