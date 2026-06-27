"""Tests for shared/cloud_mirror.py."""

from __future__ import annotations

import json
import time

import jwt
import pytest

from shared import cloud_mirror as cm
from shared import entitlement as ent
from shared.mirror_session import clear_mirror_session_for_tests
from shared.pro_settings import write_pro_settings
from shared.profile_paths import catalog_path, personal_path
from shared.supabase_auth import reset_jwks_client_for_tests


@pytest.fixture(autouse=True)
def _reset_mirror_state():
    with cm._lock:
        cm._pending.clear()
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None
    yield
    with cm._lock:
        cm._pending.clear()
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None


@pytest.fixture()
def profile_root(tmp_path, monkeypatch):
    from shared import profile_paths

    prof = tmp_path / "profiles"
    prof.mkdir(parents=True)
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}),
        encoding="utf-8",
    )
    (prof / "default").mkdir()
    (prof / "default" / "data").mkdir()
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setenv("BAKLOG_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    return tmp_path


def _enable_auth(monkeypatch):
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-test")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", "unit-test-secret")
    reset_jwks_client_for_tests()


def _pro_bearer(sub: str = "550e8400-e29b-41d4-a716-446655440000") -> str:
    token = jwt.encode(
        {
            "sub": sub,
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"plan": "pro"},
        },
        "unit-test-secret",
        algorithm="HS256",
    )
    return f"Bearer {token}"


def test_mirrorable_games_json(profile_root):
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert cm.mirrorable_relative_path(path, profile_id="default") == "games_steam.json"


def test_denies_cache_and_secrets(profile_root):
    cache_file = profile_root / "profiles" / "default" / "cache" / "auth" / "secrets.bin"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"x")
    assert cm.mirrorable_relative_path(cache_file, profile_id="default") is None


def test_schedule_and_flush_gated_when_free(profile_root, monkeypatch):
    monkeypatch.setenv("BAKLOG_PLAN", "free")
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    cm.schedule_mirror_upload(path, profile_id="default")
    cm.maybe_flush_mirror_uploads(force=True)
    assert cm._pending == {}


def test_flush_skips_when_pro_but_toggle_off(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    write_pro_settings({"cloudMirrorEnabled": False}, profile_id="default")
    ent.current_plan(_pro_bearer())
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"games":[]}', encoding="utf-8")

    uploaded: list[str] = []

    def _upload(**kwargs):
        uploaded.append(kwargs["artifact_path"])
        return {"Key": kwargs["artifact_path"]}

    monkeypatch.setattr("shared.supabase_mirror.upload_mirror_object", _upload)
    cm.schedule_mirror_upload(path, profile_id="default")
    with cm._lock:
        cm._pending["default"]["flush_at"] = time.time() - 1
    cm.maybe_flush_mirror_uploads(force=True)
    assert uploaded == []


def test_flush_uploads_when_pro_auth_and_session(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    write_pro_settings({"cloudMirrorEnabled": True}, profile_id="default")
    ent.current_plan(_pro_bearer())
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"games":[]}', encoding="utf-8")

    uploaded: list[str] = []

    def _upload(**kwargs):
        uploaded.append(kwargs["artifact_path"])
        return {"Key": kwargs["artifact_path"]}

    monkeypatch.setattr("shared.supabase_mirror.upload_mirror_object", _upload)
    monkeypatch.setattr("shared.supabase_mirror.upsert_mirror_snapshot_row", lambda **kwargs: None)

    cm.schedule_mirror_upload(path, profile_id="default")
    with cm._lock:
        cm._pending["default"]["flush_at"] = time.time() - 1
    cm.maybe_flush_mirror_uploads()
    assert uploaded == ["games_steam.json"]
    state = cm.read_mirror_upload_state(profile_id="default")
    assert state["artifacts"]["games_steam.json"]["status"] == "ok"


def test_flush_skips_without_cached_session(profile_root, monkeypatch, capsys):
    _enable_auth(monkeypatch)
    write_pro_settings({"cloudMirrorEnabled": True}, profile_id="default")
    ent.current_plan(_pro_bearer())
    clear_mirror_session_for_tests()
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    cm.schedule_mirror_upload(path, profile_id="default")
    with cm._lock:
        cm._pending["default"]["flush_at"] = time.time() - 1
    monkeypatch.setenv("BAKLOG_DEBUG", "1")
    cm.maybe_flush_mirror_uploads()
    assert "no cached bearer session" in capsys.readouterr().err


def test_personal_json_mirrorable(profile_root):
    path = personal_path(profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert cm.mirrorable_relative_path(path, profile_id="default") == "data/personal.json"


def test_debounce_coalesces_paths(profile_root):
    steam = catalog_path("games_steam.json", profile_id="default")
    gog = catalog_path("games_gog.json", profile_id="default")
    for p in (steam, gog):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    cm.schedule_mirror_upload(steam, profile_id="default")
    cm.schedule_mirror_upload(gog, profile_id="default")
    with cm._lock:
        paths = cm._pending["default"]["paths"]
    assert paths == {"games_steam.json", "games_gog.json"}


def test_mirror_read_allowed_requires_pro_jwt(profile_root, monkeypatch):
    assert cm.mirror_read_allowed(authorization=None) is False
    _enable_auth(monkeypatch)
    assert cm.mirror_read_allowed(authorization=_pro_bearer()) is True
    free = jwt.encode(
        {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"plan": "free"},
        },
        "unit-test-secret",
        algorithm="HS256",
    )
    assert cm.mirror_read_allowed(authorization=f"Bearer {free}") is False


def test_import_remote_mirror_writes_catalogs_and_personal(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    steam_doc = {"games": [{"store": "steam", "id": "570", "name": "Dota 2"}]}
    personal_doc = {
        "personal": {"steam:570": {"status": "playing"}},
        "prefs": {},
        "manual": [],
        "libraryFirstSeen": {},
    }

    monkeypatch.setattr(
        cm,
        "list_remote_mirror_artifacts",
        lambda **kwargs: [
            {"path": "games_steam.json"},
            {"path": "data/personal.json"},
        ],
    )

    def _download(**kwargs):
        path = kwargs["artifact_path"]
        if path == "games_steam.json":
            return json.dumps(steam_doc).encode("utf-8")
        if path == "data/personal.json":
            return json.dumps(personal_doc).encode("utf-8")
        raise AssertionError(path)

    monkeypatch.setattr(cm, "download_remote_mirror_artifact", _download)

    result = cm.import_remote_mirror_to_profile(authorization=_pro_bearer())
    assert result["count"] == 2
    assert "games_steam.json" in result["imported"]
    assert "data/personal.json" in result["imported"]
    assert result["personal"] is True

    saved_steam = json.loads(catalog_path("games_steam.json", profile_id="default").read_text(encoding="utf-8"))
    assert saved_steam["games"][0]["name"] == "Dota 2"
    saved_personal = json.loads(personal_path(profile_id="default").read_text(encoding="utf-8"))
    assert saved_personal["personal"]["steam:570"]["status"] == "playing"


def test_import_remote_mirror_empty_raises(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr(cm, "list_remote_mirror_artifacts", lambda **kwargs: [])
    with pytest.raises(ValueError, match="no importable"):
        cm.import_remote_mirror_to_profile(authorization=_pro_bearer())


def test_import_rejects_empty_games_catalog(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr(
        cm,
        "list_remote_mirror_artifacts",
        lambda **kwargs: [{"path": "games_steam.json"}],
    )
    monkeypatch.setattr(
        cm,
        "download_remote_mirror_artifact",
        lambda **kwargs: json.dumps({"games": []}).encode("utf-8"),
    )
    with pytest.raises(ValueError, match="empty games"):
        cm.import_remote_mirror_to_profile(authorization=_pro_bearer())


def test_import_rollback_on_catalog_failure(profile_root, monkeypatch):
    _enable_auth(monkeypatch)
    steam_doc = {"games": [{"store": "steam", "id": "570", "name": "Dota 2"}]}
    personal_doc = {
        "personal": {"steam:570": {"status": "playing"}},
        "prefs": {},
        "manual": [],
        "libraryFirstSeen": {},
    }
    local_personal = {
        "personal": {"steam:1": {"status": "backlog"}},
        "prefs": {},
        "manual": [],
        "libraryFirstSeen": {},
    }
    personal_path(profile_id="default").parent.mkdir(parents=True, exist_ok=True)
    personal_path(profile_id="default").write_text(json.dumps(local_personal), encoding="utf-8")

    monkeypatch.setattr(
        cm,
        "list_remote_mirror_artifacts",
        lambda **kwargs: [{"path": "games_steam.json"}, {"path": "data/personal.json"}],
    )

    def _download(**kwargs):
        path = kwargs["artifact_path"]
        if path == "games_steam.json":
            return json.dumps(steam_doc).encode("utf-8")
        if path == "data/personal.json":
            return json.dumps(personal_doc).encode("utf-8")
        raise AssertionError(path)

    monkeypatch.setattr(cm, "download_remote_mirror_artifact", _download)

    def _fail_import(payload):
        raise ValueError("catalog write failed")

    monkeypatch.setattr("shared.server_catalog_import.import_catalog_payload", _fail_import)

    with pytest.raises(ValueError, match="catalog write failed"):
        cm.import_remote_mirror_to_profile(authorization=_pro_bearer())

    restored = json.loads(personal_path(profile_id="default").read_text(encoding="utf-8"))
    assert restored["personal"]["steam:1"]["status"] == "backlog"
