"""fetch_itad notice path: an empty wishlist should warn, not bare-fail.

Regression for the report that ITAD "just fails" with no explanation when the
wishlist has no items. The empty-input case must exit 0 with a clear, actionable
notice and must not touch the network or overwrite an existing itad_prices.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetchers.fetch_itad as fetch_itad


@pytest.fixture
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point catalog/itad paths at a tmp dir and stub out credential + FX I/O."""
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()

    def _catalog_path(name) -> Path:
        return catalogs / str(name)

    monkeypatch.setattr(fetch_itad, "catalog_path", _catalog_path)
    monkeypatch.setattr(fetch_itad, "itad_path", lambda: catalogs / "itad_prices.json")
    monkeypatch.setattr(fetch_itad, "resolve_env", lambda *a, **k: "test-key")
    monkeypatch.setattr(fetch_itad, "ensure_fx_rates", lambda **k: None)
    # ItadClient would make network calls; the empty-input path must never reach it.
    monkeypatch.setattr(
        fetch_itad,
        "ItadClient",
        lambda *a, **k: pytest.fail("ItadClient should not be built for an empty wishlist"),
    )
    monkeypatch.setattr("sys.argv", ["fetchers.fetch_itad.py"])
    return catalogs


def test_empty_wishlist_warns_and_exits_clean(_isolated: Path, capsys):
    # No games_wishlist.json on disk -> zero titles to look up.
    exit_code = fetch_itad.main()
    assert exit_code == 0

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "wishlist is empty" in combined.lower()
    assert "skipping ITAD price fetch" in combined


def test_empty_wishlist_does_not_overwrite_existing_prices(_isolated: Path):
    # A prior successful run left prices on disk; an empty wishlist must not wipe them.
    existing = _isolated / "itad_prices.json"
    prior = {"count": 3, "by_key": {"wishlist:1": {"price": 9.99}}}
    existing.write_text(json.dumps(prior), encoding="utf-8")

    exit_code = fetch_itad.main()
    assert exit_code == 0
    assert json.loads(existing.read_text(encoding="utf-8")) == prior


def test_zero_priced_rows_refuse_before_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    existing = catalogs / "itad_prices.json"
    prior = {"count": 4, "by_key": {f"wishlist:{i}": {"price": 1} for i in range(4)}}
    existing.write_text(json.dumps(prior), encoding="utf-8")
    wishlist = catalogs / "games_wishlist.json"
    wishlist.write_text(
        json.dumps({"games": [{"appid": 1, "name": "One"}, {"appid": 2, "name": "Two"}]}),
        encoding="utf-8",
    )

    class _Client:
        def __init__(self, *a, **k):
            pass

        def lookup_title(self, title, appid=None):
            return f"plain-{title}"

        def prices_for_plains(self, plains):
            return {}

    monkeypatch.setattr(fetch_itad, "catalog_path", lambda name: catalogs / str(name))
    monkeypatch.setattr(fetch_itad, "itad_path", lambda: existing)
    monkeypatch.setattr(fetch_itad, "resolve_env", lambda *a, **k: "test-key")
    monkeypatch.setattr(fetch_itad, "ensure_fx_rates", lambda **k: None)
    monkeypatch.setattr(fetch_itad, "ItadClient", _Client)
    monkeypatch.setattr(fetch_itad, "refresh_wishlist_fx_after_itad", lambda *_a, **_k: (0, 0))
    monkeypatch.setattr("sys.argv", ["fetchers.fetch_itad.py"])

    assert fetch_itad.main() == 2
    assert json.loads(existing.read_text(encoding="utf-8")) == prior
