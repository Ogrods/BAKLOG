"""personal.json save must not auto-schedule mirror uploads (Sync now only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared import profile_paths, server_personal


@pytest.fixture()
def profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof = tmp_path / "profiles"
    prof.mkdir()
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    (prof / "index.json").write_text(
        '{"active":"default","profiles":[{"id":"default","label":"Default"}]}',
        encoding="utf-8",
    )
    root = prof / "default"
    (root / "data").mkdir(parents=True)
    (root / ".migration_complete").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(server_personal, "_rebind_after_save", lambda: None)
    return root


def test_save_personal_doc_does_not_schedule_mirror_upload(
    profile_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[Path] = []

    def _capture(path: Path, *, profile_id: str | None = None) -> None:
        scheduled.append(path)

    monkeypatch.setattr("shared.cloud_mirror.schedule_mirror_upload", _capture)
    doc = server_personal.save_personal_doc(
        {
            "personal": {"steam:a": {"status": "backlog"}},
            "prefs": {},
            "manual": [],
            "libraryFirstSeen": {},
        },
        allow_empty=True,
    )
    assert doc.get("personal", {}).get("steam:a", {}).get("status") == "backlog"
    assert scheduled == []


def test_personal_and_index_saves_fsync_before_replace(
    profile_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import safe_write

    synced: list[int] = []
    real_fsync = safe_write.os.fsync
    monkeypatch.setattr(safe_write.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])

    server_personal.save_personal_doc(
        {"personal": {"steam:a": {"status": "backlog"}}, "prefs": {}, "manual": [], "libraryFirstSeen": {}},
        allow_empty=True,
    )
    assert len(synced) == 1
    assert '"steam:a"' in server_personal.personal_path().read_text(encoding="utf-8")

    index = profile_paths.load_index()
    profile_paths.save_index(index)
    assert len(synced) == 2
    assert not list(profile_home.parent.rglob("*.tmp"))
