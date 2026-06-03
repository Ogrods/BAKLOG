"""Server drops BAKLOG_PROFILE from its own environment at import."""

from __future__ import annotations

import os

import pytest

import server


def test_release_server_profile_env_pops_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    assert server._release_server_profile_env() == "work"
    assert "BAKLOG_PROFILE" not in os.environ
    assert server._release_server_profile_env() is None


def test_module_import_already_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import-time guard runs once; override is recorded on the module."""
    # Re-import would re-run pop; test the stored override from this session's import.
    assert hasattr(server, "_SERVER_ENV_PROFILE_OVERRIDE")
