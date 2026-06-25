"""Tests for beta blind-spot patches (temp-run warn, autostart heal, Steam hint)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetchers.fetch_games as fetch_games
import shared.server_support as server_support
import shared.startup as startup
from fetchers._base import STEAM_PRIVATE_PROFILE_HINT


class _FakeRegKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_is_running_from_temp_dir_false_when_not_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server_support, "is_frozen", lambda: False)
    assert server_support.is_running_from_temp_dir(tmp_path) is False


def test_is_running_from_temp_dir_true_under_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server_support, "is_frozen", lambda: True)
    temp_root = tmp_path / "temp"
    data_dir = temp_root / "BAKLOG"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(server_support.tempfile, "gettempdir", lambda: str(temp_root))
    assert server_support.is_running_from_temp_dir(data_dir) is True


def test_is_running_from_temp_dir_false_outside_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_support, "is_frozen", lambda: True)
    data_dir = Path("C:/Users/Tester/Desktop/BAKLOG")
    monkeypatch.setattr(server_support.tempfile, "gettempdir", lambda: "C:/Users/Tester/AppData/Local/Temp")
    assert server_support.is_running_from_temp_dir(data_dir) is False


def test_is_running_from_temp_dir_marker_rar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server_support, "is_frozen", lambda: True)
    data_dir = tmp_path / "Rar$EXa0.123" / "BAKLOG"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(server_support.tempfile, "gettempdir", lambda: str(tmp_path / "elsewhere"))
    assert server_support.is_running_from_temp_dir(data_dir) is True


def test_check_data_location_prints_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server_support, "is_frozen", lambda: True)
    monkeypatch.setattr(server_support, "is_portable_frozen", lambda: False)
    monkeypatch.setattr(server_support, "frozen_bundle_dir", lambda: tmp_path)
    monkeypatch.setattr(server_support, "is_running_from_temp_dir", lambda _p: True)
    monkeypatch.setattr(server_support, "data_root", lambda: tmp_path / "BAKLOG-Data")
    server_support.check_data_location()
    captured = capsys.readouterr()
    assert "temporary folder" in captured.err


def test_reconcile_startup_removes_missing_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        startup,
        "_win_run_command",
        lambda: r'"C:\missing\BAKLOG.exe" --tray',
    )
    disabled: list[str] = []
    monkeypatch.setattr(startup, "_win_disable", lambda: disabled.append("ok"))
    assert startup.reconcile_startup() is True
    assert disabled == ["ok"]


def test_reconcile_startup_keeps_existing_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    exe = tmp_path / "BAKLOG.exe"
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(startup, "_win_run_command", lambda: f'"{exe}"')
    disabled: list[str] = []
    monkeypatch.setattr(startup, "_win_disable", lambda: disabled.append("ok"))
    assert startup.reconcile_startup() is False
    assert disabled == []


def test_reconcile_startup_noop_without_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(startup, "_win_run_command", lambda: None)
    assert startup.reconcile_startup() is False


def test_parse_win_run_target_quoted() -> None:
    target = startup._parse_win_run_target(r'"C:\Apps\BAKLOG.exe" --tray')
    assert target == Path(r"C:\Apps\BAKLOG.exe")


def test_private_profile_hint_on_empty_library(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _resolve_env(key, **_):
        return "x" if key == "STEAM_API_KEY" else "76561198000000000"

    monkeypatch.setattr(fetch_games, "resolve_env", _resolve_env)
    steam = MagicMock()
    steam.get_owned_games.return_value = []
    with patch.object(fetch_games, "load_dotenv"):
        with patch.object(fetch_games, "SteamClient", return_value=steam):
            with patch.object(fetch_games.sys, "argv", ["fetchers/fetch_games.py", "--skip-hltb"]):
                code = fetch_games.main()
    assert code == 2
    captured = capsys.readouterr()
    assert "Game details to Public" in captured.err
    assert STEAM_PRIVATE_PROFILE_HINT in captured.err


def test_update_available_compares_semver() -> None:
    assert server_support.update_available("0.7.0", "0.7.1") is True
    assert server_support.update_available("0.7.1", "0.7.0") is False
    assert server_support.update_available("0.7.0", "0.7.0") is False


def test_github_releases_api_url_matches_community_json() -> None:
    import json

    community_path = Path(__file__).resolve().parents[1] / "shared" / "community.json"
    community = json.loads(community_path.read_text(encoding="utf-8"))
    repo_url = str(community["github_repo"]).rstrip("/")
    slug = repo_url.replace("https://github.com/", "")
    api_url = server_support.github_releases_latest_api_url()
    assert api_url == f"https://api.github.com/repos/{slug}/releases/latest"
    assert "steam-backlog" not in api_url
