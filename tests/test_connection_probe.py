import json
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from auth.connection_probe import (
    STRIKE_THRESHOLD,
    clear_probe_strike,
    load_probe_state,
    probe_due,
    providers_in_auth_cooldown,
    run_connection_probe,
    save_probe_state,
)


@contextmanager
def _noop_profile_secrets(_profile_id):
    yield


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("auth.connection_probe.runs_dir", lambda *, profile_id=None: tmp_path / "runs")
    monkeypatch.setattr("auth.connection_probe._with_profile_secrets", _noop_profile_secrets)


def _status_rows(*providers):
    return [{"key": p, "status": "connected", "label": p} for p in providers]


def test_probe_due_respects_interval(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 1000.0, "strikes": {}})
    assert probe_due(pid, 1000.0 + 3599, 3600) is False
    assert probe_due(pid, 1000.0 + 3600, 3600) is True


def test_providers_in_auth_cooldown_maps_fetcher_to_provider():
    now = time.time()
    history = [{"key": "steam", "failure_kind": "auth", "ended_at": now - 60}]
    assert providers_in_auth_cooldown(history, now) == {"steam"}


def test_two_strikes_flip_to_expired(tmp_path):
    pid = "prof"
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet", return_value="auth_fail"):
            with patch("auth.connection_probe.mark_verified") as verified:
                with patch("auth.connection_probe.mark_invalid") as invalid:
                    run_connection_probe(pid, now=100.0, history=[])
                    assert invalid.call_count == 0
                    state = load_probe_state(pid)
                    assert state["strikes"]["gog"] == 1
                    run_connection_probe(pid, now=200.0, history=[])
                    invalid.assert_called_once_with("gog", error="Session rejected by provider")
                    state = load_probe_state(pid)
                    assert state["strikes"]["gog"] == 0
                    verified.assert_not_called()


def test_ok_resets_strikes_and_marks_verified(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 0, "strikes": {"gog": 1}})
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet", return_value="ok"):
            with patch("auth.connection_probe.mark_verified") as verified:
                with patch("auth.connection_probe.mark_invalid") as invalid:
                    run_connection_probe(pid, now=100.0, history=[])
                    verified.assert_called_once_with("gog")
                    invalid.assert_not_called()
                    assert load_probe_state(pid)["strikes"]["gog"] == 0


def test_unreachable_does_not_increment_strikes(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 0, "strikes": {"steam": 1}})
    with patch("auth.connection_probe.get_status", return_value=_status_rows("steam")):
        with patch("auth.connection_probe.probe_provider_quiet", return_value="unreachable"):
            with patch("auth.connection_probe.mark_verified") as verified:
                with patch("auth.connection_probe.mark_invalid") as invalid:
                    run_connection_probe(pid, now=100.0, history=[])
                    verified.assert_not_called()
                    invalid.assert_not_called()
                    assert load_probe_state(pid)["strikes"]["steam"] == 1


def test_skips_non_connected_providers(tmp_path):
    pid = "prof"
    rows = [{"key": "gog", "status": "disconnected", "label": "GOG"}]
    with patch("auth.connection_probe.get_status", return_value=rows):
        with patch("auth.connection_probe.probe_provider_quiet") as probe:
            results = run_connection_probe(pid, now=100.0, history=[])
            probe.assert_not_called()
            assert results == {}


def test_skips_providers_in_auth_cooldown(tmp_path):
    pid = "prof"
    now = time.time()
    history = [{"key": "gog", "failure_kind": "auth", "ended_at": now - 60}]
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet") as probe:
            results = run_connection_probe(pid, now=now, history=history)
            probe.assert_not_called()
            assert results == {"gog": "skipped_cooldown"}


def test_does_not_write_catalog_or_run_history(tmp_path, monkeypatch):
    pid = "prof"
    runs = tmp_path / "runs"
    runs.mkdir(parents=True)
    catalog = tmp_path / "games_gog.json"
    catalog.write_text(json.dumps({"fetched_at": 1, "games": []}), encoding="utf-8")
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet", return_value="ok"):
            with patch("auth.connection_probe.mark_verified"):
                run_connection_probe(pid, now=100.0, history=[])
    assert json.loads(catalog.read_text(encoding="utf-8"))["fetched_at"] == 1
    assert not (runs / "history.json").exists()


def test_strike_threshold_constant():
    assert STRIKE_THRESHOLD == 2


def test_last_probe_not_advanced_on_cooldown_only(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 500.0, "strikes": {}})
    now = time.time()
    history = [{"key": "gog", "failure_kind": "auth", "ended_at": now - 60}]
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet") as probe:
            results = run_connection_probe(pid, now=now, history=history)
            probe.assert_not_called()
    assert results == {"gog": "skipped_cooldown"}
    assert load_probe_state(pid)["last_probe"] == 500.0


def test_clear_probe_strike_removes_provider_strike(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 0, "strikes": {"gog": 1, "steam": 2}})
    clear_probe_strike(pid, "gog")
    state = load_probe_state(pid)
    assert "gog" not in state["strikes"]
    assert state["strikes"]["steam"] == 2
    clear_probe_strike(pid, "psn")
    assert state["strikes"]["steam"] == 2


def test_mark_connected_clears_probe_strike(tmp_path, monkeypatch):
    pid = "prof"
    monkeypatch.setattr("auth.manager.get_active_profile_id", lambda: pid)
    save_probe_state(pid, {"last_probe": 0, "strikes": {"gog": 1}})
    with patch("auth.manager.get_provider_blob", return_value={}):
        with patch("auth.manager.set_provider_blob"):
            from auth.manager import mark_connected

            mark_connected("gog", {"GOG_AL": "cookie"})
    assert "gog" not in load_probe_state(pid)["strikes"]


def test_one_strike_after_reconnect_requires_two_fails_again(tmp_path):
    pid = "prof"
    save_probe_state(pid, {"last_probe": 0, "strikes": {"gog": 1}})
    clear_probe_strike(pid, "gog")
    with patch("auth.connection_probe.get_status", return_value=_status_rows("gog")):
        with patch("auth.connection_probe.probe_provider_quiet", return_value="auth_fail"):
            with patch("auth.connection_probe.mark_invalid") as invalid:
                run_connection_probe(pid, now=100.0, history=[])
                assert invalid.call_count == 0
                assert load_probe_state(pid)["strikes"]["gog"] == 1
                run_connection_probe(pid, now=200.0, history=[])
                invalid.assert_called_once()
