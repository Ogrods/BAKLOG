"""Supabase mirror list helpers - non-recursive Storage list regression."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import pytest

from shared import supabase_mirror


def test_list_mirror_artifacts_joins_data_subfolder(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_list_prefix(*, prefix: str, bearer_token: str, limit: int = 200) -> list[dict[str, Any]]:
        calls.append(prefix)
        if prefix.endswith("/data") or prefix.endswith("/data/"):
            return [
                {
                    "name": "personal.json",
                    "id": "obj-personal",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "metadata": {},
                }
            ]
        # Immediate children: catalog file + folder marker for data/
        return [
            {
                "name": "games_steam.json",
                "id": "obj-steam",
                "updated_at": "2026-01-01T00:00:00Z",
                "metadata": {},
            },
            {"name": "data", "id": None, "updated_at": None, "metadata": None},
        ]

    monkeypatch.setattr(supabase_mirror, "_list_prefix", fake_list_prefix)
    rows = supabase_mirror.list_mirror_artifacts(
        user_id="user-1", profile_id="default", bearer_token="tok"
    )
    names = [r["name"] for r in rows]
    assert "games_steam.json" in names
    assert "data/personal.json" in names
    assert "data" not in names
    assert any(c.endswith("/data") or c.endswith("default/data") for c in calls)


def test_list_mirror_profile_ids_filters_folders(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list_prefix(*, prefix: str, bearer_token: str, limit: int = 200) -> list[dict[str, Any]]:
        assert prefix == "user-1/"
        return [
            {"name": "default", "id": None},
            {"name": "11111111-1111-1111-1111-111111111111", "id": None},
            {"name": "games_steam.json", "id": "obj"},  # file at user root - skip
            {"name": "nested/path", "id": None},  # invalid
            {"name": "..", "id": None},
        ]

    monkeypatch.setattr(supabase_mirror, "_list_prefix", fake_list_prefix)
    ids = supabase_mirror.list_mirror_profile_ids(user_id="user-1", bearer_token="tok")
    assert ids == ["11111111-1111-1111-1111-111111111111", "default"]


def test_list_prefix_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_json_request(req):  # noqa: ANN001
        body = json.loads(req.data.decode("utf-8"))
        calls.append(int(body.get("offset") or 0))
        offset = calls[-1]
        if offset == 0:
            return [{"name": f"f{i}.json", "id": f"id-{i}"} for i in range(3)]
        return [{"name": "last.json", "id": "id-last"}]

    monkeypatch.setattr(supabase_mirror, "_base_url", lambda: "https://example.test")
    monkeypatch.setattr(supabase_mirror, "_anon_key", lambda: "anon")
    monkeypatch.setattr(supabase_mirror, "_json_request", fake_json_request)
    rows = supabase_mirror._list_prefix(prefix="u/p", bearer_token="tok", limit=3)
    assert calls == [0, 3]
    assert len(rows) == 4
    assert rows[-1]["name"] == "last.json"


def test_delete_mirror_objects_builds_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_json_request(req):  # noqa: ANN001
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return {}

    monkeypatch.setattr(supabase_mirror, "_base_url", lambda: "https://example.test")
    monkeypatch.setattr(supabase_mirror, "_anon_key", lambda: "anon")
    monkeypatch.setattr(supabase_mirror, "_json_request", fake_json_request)
    deleted = supabase_mirror.delete_mirror_objects(
        user_id="user-1",
        profile_id="default",
        artifact_paths=["games_steam.json", "data/personal.json"],
        bearer_token="tok",
    )
    assert deleted == ["games_steam.json", "data/personal.json"]
    assert seen["method"] == "DELETE"
    assert seen["body"] == [
        "user-1/default/games_steam.json",
        "user-1/default/data/personal.json",
    ]


def test_delete_mirror_snapshot_rows_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_json_request(req):  # noqa: ANN001
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        return {}

    monkeypatch.setattr(supabase_mirror, "_base_url", lambda: "https://example.test")
    monkeypatch.setattr(supabase_mirror, "_anon_key", lambda: "anon")
    monkeypatch.setattr(supabase_mirror, "_json_request", fake_json_request)
    supabase_mirror.delete_mirror_snapshot_rows(
        user_id="user-1",
        profile_id="default",
        bearer_token="tok",
        artifact_paths=["games_steam.json"],
    )
    assert seen["method"] == "DELETE"
    assert "user_id=eq.user-1" in seen["url"]
    assert "profile_id=eq.default" in seen["url"]
    assert "artifact_path=in." in seen["url"]
    assert "games_steam.json" in urllib.parse.unquote(seen["url"])
