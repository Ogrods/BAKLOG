"""Supabase mirror list helpers - non-recursive Storage list regression."""

from __future__ import annotations

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


def test_mirror_object_key_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        supabase_mirror.mirror_object_key("u", "p", "../secrets.bin")
