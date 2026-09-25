"""fetch_itad prices every connected wishlist, tags match provenance, and caps new lookups."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetchers.fetch_itad as fetch_itad


def _price(amount: float) -> dict:
    return {"shop": "Steam", "price": amount, "currency": "USD", "regular": 20.0, "cut": 50}


class _Client:
    cached: set[tuple[str, int | None]] = set()
    lookups: list[tuple[str, int | None]] = []

    def __init__(self, *a, **k):
        pass

    def is_lookup_cached(self, title, appid=None):
        return (title, appid) in self.cached

    def lookup_title(self, title, appid=None):
        self.lookups.append((title, appid))
        return f"plain-{title}"

    def prices_for_plains(self, plains):
        return {p: _price(9.99) for p in plains}


@pytest.fixture
def catalogs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "catalogs"
    root.mkdir()
    _Client.cached = set()
    _Client.lookups = []
    monkeypatch.setattr(fetch_itad, "catalog_path", lambda name: root / str(name))
    monkeypatch.setattr(fetch_itad, "itad_path", lambda: root / "itad_prices.json")
    monkeypatch.setattr(fetch_itad, "resolve_env", lambda *a, **k: "test-key")
    monkeypatch.setattr(fetch_itad, "ensure_fx_rates", lambda **k: None)
    monkeypatch.setattr(fetch_itad, "ItadClient", _Client)
    monkeypatch.setattr(fetch_itad, "refresh_wishlist_fx_after_itad", lambda *_a, **_k: (0, 0))
    monkeypatch.setattr("sys.argv", ["fetchers.fetch_itad.py"])
    return root


def _write(root: Path, name: str, games: list[dict]) -> None:
    (root / name).write_text(json.dumps({"games": games}), encoding="utf-8")


def test_prices_all_wishlist_stores_with_frontend_keys(catalogs: Path):
    _write(catalogs, "games_wishlist.json", [{"appid": 570, "name": "Dota 2"}])
    _write(catalogs, "games_wishlist_gog.json", [{"id": "111", "gog_id": "111", "name": "Gog Game"}])
    _write(
        catalogs,
        "games_wishlist_epic.json",
        [{"id": "epic-ns:off", "name": "Epic Game", "steam_appid": 1091500}],
    )
    _write(catalogs, "games_wishlist_xbox.json", [{"xbox_product_id": "9N", "name": "Xbox Game"}])

    assert fetch_itad.main() == 0

    by_key = json.loads((catalogs / "itad_prices.json").read_text(encoding="utf-8"))["by_key"]
    assert set(by_key) == {"wishlist:570", "wishlist:gog-111", "wishlist:epic-ns:off", "wishlist:xbox-9N"}
    assert by_key["wishlist:570"]["match"] == "appid"
    assert by_key["wishlist:epic-ns:off"]["match"] == "appid"
    assert by_key["wishlist:gog-111"]["match"] == "title"
    assert by_key["wishlist:xbox-9N"]["match"] == "title"
    assert ("Epic Game", 1091500) in _Client.lookups
    assert ("Gog Game", None) in _Client.lookups


def test_same_title_on_two_stores_gets_two_rows(catalogs: Path):
    _write(catalogs, "games_wishlist.json", [{"appid": 1, "name": "Hades"}])
    _write(catalogs, "games_wishlist_gog.json", [{"id": "9", "name": "Hades"}])

    assert fetch_itad.main() == 0

    by_key = json.loads((catalogs / "itad_prices.json").read_text(encoding="utf-8"))["by_key"]
    assert set(by_key) == {"wishlist:1", "wishlist:gog-9"}
    assert by_key["wishlist:1"] is not by_key["wishlist:gog-9"]


def test_rows_without_ids_or_names_are_skipped(catalogs: Path):
    _write(
        catalogs,
        "games_wishlist_psn.json",
        [{"name": "No id"}, {"psn_product_id": "UP1", "name": ""}, {"psn_product_id": "UP2", "name": "Ok"}],
    )

    assert fetch_itad.main() == 0

    by_key = json.loads((catalogs / "itad_prices.json").read_text(encoding="utf-8"))["by_key"]
    assert set(by_key) == {"wishlist:psn-UP2"}


def test_uncached_lookup_budget_defers_extra_titles(catalogs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fetch_itad, "ITAD_LOOKUP_BUDGET", 2)
    games = [{"appid": i, "name": f"Game {i}"} for i in range(1, 6)]
    _write(catalogs, "games_wishlist.json", games)
    _Client.cached = {("Game 5", 5)}

    assert fetch_itad.main() == 0

    by_key = json.loads((catalogs / "itad_prices.json").read_text(encoding="utf-8"))["by_key"]
    assert set(by_key) == {"wishlist:1", "wishlist:2", "wishlist:5"}


def test_deferred_titles_keep_prior_prices(catalogs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fetch_itad, "ITAD_LOOKUP_BUDGET", 1)
    _write(catalogs, "games_wishlist.json", [{"appid": 1, "name": "A"}, {"appid": 2, "name": "B"}])
    prior = {"count": 1, "by_key": {"wishlist:2": {"price": 4.0}}}
    (catalogs / "itad_prices.json").write_text(json.dumps(prior), encoding="utf-8")

    assert fetch_itad.main() == 0

    by_key = json.loads((catalogs / "itad_prices.json").read_text(encoding="utf-8"))["by_key"]
    assert by_key["wishlist:2"] == {"price": 4.0}
    assert by_key["wishlist:1"]["match"] == "appid"
