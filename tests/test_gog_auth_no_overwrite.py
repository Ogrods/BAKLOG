"""GOG auth failure must exit 4 and leave the on-disk catalog untouched."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clients.gog_client import GOG_AUTH_MESSAGE, GogAuthError
from fetchers._progress import EXIT_CODE_AUTH


def test_gog_auth_error_exits_4_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fetchers.fetch_gog as fetch_gog

    out = tmp_path / "games_gog.json"
    cached = {
        "fetched_at": "2024-01-01T00:00:00+00:00",
        "store": "gog",
        "source": "web",
        "game_count": 2,
        "games": [
            {"id": 1, "gog_id": 1, "name": "Real Title One", "source": "web"},
            {"id": 2, "gog_id": 2, "name": "Real Title Two", "source": "web"},
        ],
    }
    out.write_text(json.dumps(cached), encoding="utf-8")
    before = out.read_text(encoding="utf-8")

    monkeypatch.setattr(fetch_gog, "catalog_file", lambda _p: out)
    monkeypatch.setattr(fetch_gog, "write_catalog_text", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("must not write catalog on auth failure")
    ))
    monkeypatch.setattr(fetch_gog, "resolve_env", lambda *_a, **_k: "gog-al-token")
    monkeypatch.setattr(fetch_gog, "probe_gog_session", lambda *_a, **_k: None)
    monkeypatch.setattr(fetch_gog, "resolve_source", lambda *_a, **_k: "web")
    monkeypatch.setattr(fetch_gog, "_galaxy_db_ready", lambda *_a, **_k: False)
    monkeypatch.setattr(sys, "argv", ["fetch_gog", "--source", "web", "--skip-hltb"])

    mark_calls: list = []
    monkeypatch.setattr(
        fetch_gog, "mark_invalid", lambda *a, **k: mark_calls.append((a, k))
    )

    client = MagicMock()
    client.get_all_filtered_products.side_effect = GogAuthError(GOG_AUTH_MESSAGE)
    client.get_owned_game_ids.return_value = [1, 2, 3]
    monkeypatch.setattr(fetch_gog, "GogClient", lambda *_a, **_k: client)

    assert fetch_gog.main() == EXIT_CODE_AUTH
    assert mark_calls
    assert out.read_text(encoding="utf-8") == before
    client.get_owned_game_ids.assert_not_called()


def test_gog_placeholder_collapse_refuses() -> None:
    import fetchers.fetch_gog as fetch_gog

    games = [{"name": f"GOG {i}"} for i in range(10)]
    assert fetch_gog.refuse_gog_placeholder_collapse(games, allow_drift=False) == 3
    assert fetch_gog.refuse_gog_placeholder_collapse(games, allow_drift=True) is None
    mixed = [{"name": "Real"} for _ in range(8)] + [{"name": "GOG 1"}, {"name": "GOG 2"}]
    assert fetch_gog.refuse_gog_placeholder_collapse(mixed, allow_drift=False) is None
