"""Steam wishlist enrich must not invent Steam {appid} placeholders."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_wishlist_failed_details_preserves_existing_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fetchers.fetch_wishlist as fw

    out = tmp_path / "games_wishlist.json"
    existing = {
        "games": [
            {"id": 10, "appid": 10, "name": "Cached Good Name", "store": "wishlist"},
            {"id": 20, "appid": 20, "name": "Other Cached", "store": "wishlist"},
        ],
        "game_count": 2,
    }
    out.write_text(json.dumps(existing), encoding="utf-8")

    written: list[str] = []

    def _write(path, text):  # noqa: ANN001
        written.append(text)
        Path(path).write_text(text, encoding="utf-8")
        return Path(path)

    monkeypatch.setattr(fw, "GAMES_WISHLIST_JSON", out)
    monkeypatch.setattr(fw, "write_catalog_text", _write)
    monkeypatch.setattr(fw, "load_existing_games", lambda _p: {
        str(g["appid"]): g for g in existing["games"]
    })
    monkeypatch.setattr(fw, "resolve_env", lambda key, provider=None: "x")
    monkeypatch.setattr(
        fw,
        "fetch_wishlist_items",
        lambda *_a, **_k: [{"appid": 10}, {"appid": 30}],
    )
    monkeypatch.setattr(fw, "run_with_heartbeat", lambda fn, *_a, **_k: fn())
    monkeypatch.setattr(sys, "argv", ["fetch_wishlist", "--skip-hltb"])

    steam = MagicMock()
    steam.get_app_details.side_effect = RuntimeError("store down")
    steam.get_review_summary.return_value = None
    monkeypatch.setattr(fw, "SteamClient", lambda *_a, **_k: steam)
    monkeypatch.setattr(fw, "HltbClient", MagicMock)

    assert fw.main() == 0
    assert written, "expected a successful write with preserved rows"
    payload = json.loads(written[-1])
    names = {g["appid"]: g["name"] for g in payload["games"]}
    assert names[10] == "Cached Good Name"
    assert 30 not in names  # no Steam 30 placeholder for brand-new miss
    assert all(not str(n).startswith("Steam ") for n in names.values())


def test_wishlist_placeholder_collapse_refuses_similar_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fetchers.fetch_wishlist as fw

    out = tmp_path / "games_wishlist.json"
    out.write_text(
        json.dumps({"games": [{"name": f"Real {i}"} for i in range(10)], "game_count": 10}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fetchers._base._previous_game_count",
        lambda _p: 10,
    )
    stubs = [{"name": f"Steam {i}"} for i in range(10)]
    assert (
        fw.refuse_wishlist_placeholder_collapse(
            stubs, allow_drift=False, output_path=out
        )
        == 3
    )
