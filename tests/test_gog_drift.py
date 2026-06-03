"""Tests for per-source drift guards on GOG and itch fetchers."""

from __future__ import annotations

import json
from pathlib import Path

import fetch_gog as fg
import fetch_itch as fi


def _write_gog_catalog(path: Path, games: list[dict]) -> None:
    path.write_text(
        json.dumps({"games": games, "game_count": len(games)}, indent=2),
        encoding="utf-8",
    )


def test_refuse_gog_source_drift_blocks_sharp_drop(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "games_gog.json"
    _write_gog_catalog(
        out,
        [{"id": i, "gog_id": i, "source": "local", "name": f"G{i}"} for i in range(10)],
    )
    monkeypatch.setattr(fg, "catalog_file", lambda _p: out)
    code = fg.refuse_gog_source_drift(
        2, source="local", allow_drift=False, output_path=out
    )
    assert code == 3


def test_refuse_gog_source_drift_allow_drift(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "games_gog.json"
    _write_gog_catalog(
        out,
        [{"id": 1, "gog_id": 1, "source": "web", "name": "A"}],
    )
    monkeypatch.setattr(fg, "catalog_file", lambda _p: out)
    assert (
        fg.refuse_gog_source_drift(0, source="web", allow_drift=True, output_path=out)
        is None
    )


def test_refuse_itch_source_drift_blocks_sharp_drop(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "games_itch.json"
    path_data = {
        "games": [
            {"id": i, "itch_id": i, "source": "api", "name": f"G{i}"}
            for i in range(8)
        ],
        "game_count": 8,
    }
    out.write_text(json.dumps(path_data), encoding="utf-8")
    monkeypatch.setattr(fi, "catalog_file", lambda _p: out)
    code = fi.refuse_itch_source_drift(
        1, source="api", allow_drift=False, output_path=out
    )
    assert code == 3
