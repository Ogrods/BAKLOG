"""Unit tests for shared.cloud_mirror allowlist, path safety, and active-profile import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shared import cloud_mirror, mirror_artifacts, profile_paths
from shared.cloud_mirror import (
    MirrorProfileMismatch,
    _mirror_artifact_write_path,
    _validate_mirror_staged_doc,
    import_remote_mirror_to_profile,
    schedule_mirror_upload,
)
from shared.mirror_artifacts import is_allowed_relative, is_denied_relative


@pytest.fixture()
def profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof = tmp_path / "profiles"
    prof.mkdir()
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}),
        encoding="utf-8",
    )
    root = prof / "default"
    (root / "data").mkdir(parents=True)
    (root / ".migration_complete").write_text("1\n", encoding="utf-8")
    return root


def test_allowlist_table() -> None:
    assert is_allowed_relative("games_steam.json")
    assert is_allowed_relative("games_wishlist_gog.json")
    assert is_allowed_relative("itad_prices.json")
    assert is_allowed_relative("data/personal.json")
    assert not is_allowed_relative("free_claims.json")
    assert not is_allowed_relative("Games_steam.json")
    assert not is_allowed_relative("cache/auth/secrets.bin")


def test_traversal_denied(profile_home: Path) -> None:
    assert is_denied_relative("../games_steam.json")
    assert is_denied_relative("data/../../etc/passwd")
    assert mirror_artifacts.mirrorable_relative_path(
        Path("/etc/passwd"), profile_root=profile_home
    ) is None
    assert cloud_mirror.mirrorable_relative_path(profile_home / ".." / "other" / "x.json") is None


def test_write_path_stays_under_profile(profile_home: Path) -> None:
    path = _mirror_artifact_write_path("games_steam.json", profile_id="default")
    assert path.resolve().is_relative_to(profile_home.resolve())
    with pytest.raises(ValueError):
        _mirror_artifact_write_path("free_claims.json", profile_id="default")


def test_validate_rejects_unknown_artifact() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _validate_mirror_staged_doc("notes.txt", {"a": 1}, allow_empty_catalogs=False)


def test_schedule_too_large_records_status(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_mirror, "mirror_upload_allowed", lambda **_: True)
    big = profile_home / "games_steam.json"
    big.write_bytes(b"x" * (cloud_mirror.MIRROR_MAX_UPLOAD_BYTES + 1))
    schedule_mirror_upload(big, profile_id="default")
    state = cloud_mirror.read_mirror_upload_state(profile_id="default")
    assert state["artifacts"]["games_steam.json"]["status"] == "too_large"


def test_import_non_active_profile_raises(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )
    monkeypatch.setattr(
        cloud_mirror,
        "list_remote_mirror_artifacts",
        lambda **_: [{"path": "games_steam.json"}],
    )
    with pytest.raises(MirrorProfileMismatch):
        import_remote_mirror_to_profile(
            authorization="Bearer x",
            profile_id="other",
            source_profile_id="default",
            paths=["games_steam.json"],
        )


def test_import_from_other_cloud_source(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = profile_home / "games_steam.json"
    catalog.write_text(
        json.dumps({"games": [{"id": "1", "title": "Old"}], "store": "steam", "game_count": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )
    seen: dict[str, str] = {}

    def _list(**kwargs):
        seen["list_profile"] = str(kwargs.get("profile_id") or "")
        return [{"path": "games_steam.json"}]

    def _download(*, authorization: str, artifact_path: str, profile_id: str | None = None) -> bytes:
        seen["download_profile"] = str(profile_id or "")
        return json.dumps(
            {"games": [{"id": "9", "title": "From guest"}], "store": "steam", "game_count": 1}
        ).encode()

    monkeypatch.setattr(cloud_mirror, "list_remote_mirror_artifacts", _list)
    monkeypatch.setattr(cloud_mirror, "download_remote_mirror_artifact", _download)
    monkeypatch.setattr("shared.server_personal._rebind_after_save", lambda: None)

    result = import_remote_mirror_to_profile(
        authorization="Bearer x",
        source_profile_id="guest",
        include_personal=False,
    )
    assert seen["list_profile"] == "guest"
    assert seen["download_profile"] == "guest"
    assert result.get("sourceProfile") == "guest"
    assert result.get("profile") == "default"
    rewritten = json.loads(catalog.read_text(encoding="utf-8"))
    assert rewritten["games"][0]["id"] == "9"


def test_prefer_mirror_source_profile_order() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    assert cloud_mirror.prefer_mirror_source_profile(
        ["guest", "default", uid], active_profile_id="default", user_id=uid
    ) == "default"
    assert cloud_mirror.prefer_mirror_source_profile(
        ["guest", uid], active_profile_id="missing", user_id=uid
    ) == uid
    assert cloud_mirror.prefer_mirror_source_profile(
        ["guest", "default"], active_profile_id="x", user_id=uid
    ) == "default"


def test_import_rollback_on_failure(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = profile_home / "games_steam.json"
    prior = {"games": [{"id": "1", "title": "Keep"}], "store": "steam", "game_count": 1}
    catalog.write_text(json.dumps(prior), encoding="utf-8")

    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )
    monkeypatch.setattr(
        cloud_mirror,
        "list_remote_mirror_artifacts",
        lambda **_: [{"path": "games_steam.json"}, {"path": "data/personal.json"}],
    )

    def _download(*, authorization: str, artifact_path: str, profile_id: str | None = None) -> bytes:
        if artifact_path == "games_steam.json":
            return json.dumps(
                {"games": [{"id": "2", "title": "New"}], "store": "steam", "game_count": 1}
            ).encode()
        return json.dumps({"statuses": {}, "notes": {}}).encode()

    monkeypatch.setattr(cloud_mirror, "download_remote_mirror_artifact", _download)

    def _boom(doc: dict[str, Any], *, allow_empty: bool = False) -> dict[str, Any]:
        raise RuntimeError("personal save failed")

    monkeypatch.setattr("shared.server_personal.save_personal_doc", _boom)

    with pytest.raises(RuntimeError, match="personal save failed"):
        import_remote_mirror_to_profile(
            authorization="Bearer x",
            source_profile_id="default",
            include_personal=True,
        )

    restored = json.loads(catalog.read_text(encoding="utf-8"))
    assert restored["games"][0]["id"] == "1"


def test_import_successful_overwrite(profile_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = profile_home / "games_steam.json"
    catalog.write_text(
        json.dumps({"games": [{"id": "1", "title": "Old"}], "store": "steam", "game_count": 1}),
        encoding="utf-8",
    )
    personal = profile_home / "data" / "personal.json"
    personal.write_text(
        json.dumps(
            {
                "personal": {"steam:1": {"status": "backlog"}},
                "prefs": {},
                "manual": [],
                "libraryFirstSeen": {},
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )
    monkeypatch.setattr(
        cloud_mirror,
        "list_remote_mirror_artifacts",
        lambda **_: [{"path": "games_steam.json"}, {"path": "data/personal.json"}],
    )

    def _download(*, authorization: str, artifact_path: str, profile_id: str | None = None) -> bytes:
        if artifact_path == "games_steam.json":
            return json.dumps(
                {"games": [{"id": "9", "title": "Imported"}], "store": "steam", "game_count": 1}
            ).encode()
        return json.dumps(
            {
                "personal": {"steam:9": {"status": "playing", "notes": "from cloud"}},
                "prefs": {},
                "manual": [],
                "libraryFirstSeen": {},
                "schema_version": 1,
            }
        ).encode()

    monkeypatch.setattr(cloud_mirror, "download_remote_mirror_artifact", _download)
    # Avoid importing server during personal save in unit test.
    monkeypatch.setattr("shared.server_personal._rebind_after_save", lambda: None)

    result = import_remote_mirror_to_profile(
        authorization="Bearer x",
        source_profile_id="default",
        include_personal=True,
    )
    assert "games_steam.json" in (result.get("imported") or [])
    assert result.get("personal") is True
    rewritten = json.loads(catalog.read_text(encoding="utf-8"))
    assert rewritten["games"][0]["id"] == "9"
    personal_doc = json.loads(personal.read_text(encoding="utf-8"))
    assert personal_doc.get("personal", {}).get("steam:9", {}).get("status") == "playing"


def test_mirror_upload_blocked_when_capability_soon(
    profile_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "soon")
    monkeypatch.setattr(cloud_mirror, "is_pro_background", lambda: True)
    monkeypatch.setattr(
        cloud_mirror,
        "read_pro_settings",
        lambda **_: {"cloudMirrorEnabled": True},
    )
    assert cloud_mirror.mirror_upload_allowed(profile_id="default") is False


def test_mirror_upload_allowed_when_capability_live(
    profile_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "live")
    monkeypatch.setattr(cloud_mirror, "is_pro_background", lambda: True)
    monkeypatch.setattr(
        cloud_mirror,
        "read_pro_settings",
        lambda **_: {"cloudMirrorEnabled": True},
    )
    assert cloud_mirror.mirror_upload_allowed(profile_id="default") is True
