import json

import pytest

from shared import profile_paths
from shared.profiles import create_profile, set_active_profile


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    prof_dir = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    return tmp_path


def test_run_append_history_uses_pinned_profile(isolated_profiles):
    import server

    create_profile("Work")
    default_runs = profile_paths.runs_dir(profile_id="default")
    work_runs = profile_paths.runs_dir(profile_id="work")
    default_runs.mkdir(parents=True, exist_ok=True)
    work_runs.mkdir(parents=True, exist_ok=True)
    mgr = server.RunManager(runs_dir=default_runs)
    summary = {"id": "abc", "key": "steam", "label": "Steam", "status": "done", "exit_code": 0}
    mgr._append_history(summary, profile_id="work")
    hist = json.loads((work_runs / "history.json").read_text(encoding="utf-8"))
    assert hist[0]["id"] == "abc"
    assert not (default_runs / "history.json").exists()
    set_active_profile("work")
    server._refresh_personal_paths()
    mgr.rebind_profile_paths()
    assert mgr._runs_dir == profile_paths.runs_dir()
    assert list(mgr._history)[0]["id"] == "abc"
