import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

import server
from shared import profile_paths
from shared.profiles import create_profile, set_active_profile


@pytest.fixture()
def isolated_profiles(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    (prof / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    return tmp_path


@pytest.fixture()
def multi_profile_server(isolated_profiles, monkeypatch):
    tmp_path = isolated_profiles
    monkeypatch.setattr(server, "ROOT", tmp_path)
    server._refresh_personal_paths()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(tmp_path)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _request(base, method, path):
    headers = {}
    if method != "GET":
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    req = urllib.request.Request(f"{base}{path}", headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return (resp.status, json.loads(raw))
            except json.JSONDecodeError:
                return (resp.status, raw)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return (exc.code, parsed)


def test_run_accessible_hides_other_profile_run(isolated_profiles):
    create_profile("Work")
    create_profile("Play")
    set_active_profile("default")
    mgr = server.RunManager(runs_dir=profile_paths.runs_dir(profile_id="default"))
    work_run = server.Run("steam", runs_dir=profile_paths.runs_dir(profile_id="work"), profile_id="work")
    work_run.status = "done"
    with mgr._lock:
        mgr._runs_by_id[work_run.id] = work_run
    assert server._run_accessible(mgr.get(work_run.id)) is None
    set_active_profile("work")
    assert server._run_accessible(mgr.get(work_run.id)) is not None


def test_rebind_drops_other_profile_runs_from_memory(isolated_profiles, monkeypatch):
    create_profile("Work")
    mgr = server.RunManager(runs_dir=profile_paths.runs_dir(profile_id="default"))
    work_run = server.Run("steam", runs_dir=profile_paths.runs_dir(profile_id="work"), profile_id="work")
    default_run = server.Run("steam", runs_dir=profile_paths.runs_dir(profile_id="default"), profile_id="default")
    with mgr._lock:
        mgr._runs_by_id[work_run.id] = work_run
        mgr._runs_by_id[default_run.id] = default_run
    set_active_profile("work")
    mgr.rebind_profile_paths()
    assert work_run.id in mgr._runs_by_id
    assert default_run.id not in mgr._runs_by_id


def test_cancel_and_stream_return_404_for_other_profile_run(multi_profile_server):
    base = multi_profile_server
    create_profile("Work")
    create_profile("Play")
    mgr = server.MANAGER
    work_run = server.Run("steam", runs_dir=profile_paths.runs_dir(profile_id="work"), profile_id="work")
    work_run.status = "done"
    work_run.mark_finished()
    with mgr._lock:
        mgr._runs_by_id[work_run.id] = work_run
    set_active_profile("play")
    server._refresh_personal_paths()
    cancel_status, _ = _request(base, "POST", f"/api/run/{work_run.id}/cancel")
    assert cancel_status == 404
    stream_status, _ = _request(base, "GET", f"/api/stream/{work_run.id}")
    assert stream_status == 404


def test_runs_snapshot_filters_other_profile_history(multi_profile_server, isolated_profiles):
    base = multi_profile_server
    create_profile("Work")
    create_profile("Play")
    mgr = server.MANAGER
    work_summary = {
        "id": "workhist1",
        "key": "steam",
        "label": "Steam",
        "status": "done",
        "exit_code": 0,
        "profile_id": "work",
    }
    play_summary = {
        "id": "playhist1",
        "key": "gog",
        "label": "GOG",
        "status": "done",
        "exit_code": 0,
        "profile_id": "play",
    }
    mgr._append_history(work_summary, profile_id="work")
    mgr._append_history(play_summary, profile_id="play")
    set_active_profile("play")
    server._refresh_personal_paths()
    status, body = _request(base, "GET", "/api/runs")
    assert status == 200
    history_ids = [h.get("id") for h in body.get("history") or []]
    assert "playhist1" in history_ids
    assert "workhist1" not in history_ids
