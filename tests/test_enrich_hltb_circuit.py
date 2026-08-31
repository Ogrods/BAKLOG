"""Offline tests for enrich_hltb circuit breaker + catalog checkpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from shared.profile_paths import DEFAULT_PROFILE_ID

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shared.profile_paths.profile_root", lambda profile_id=None: tmp_path)
    monkeypatch.setattr(
        "shared.profile_paths.get_active_profile_id",
        lambda: DEFAULT_PROFILE_ID,
    )
    monkeypatch.setattr("auth.manager.get_active_profile_id", lambda: DEFAULT_PROFILE_ID)
    (tmp_path / "cache").mkdir()
    games = [
        {"id": str(i), "name": f"Game {i}", "hltb_main_hours": None}
        for i in range(1, 41)
    ]
    (tmp_path / "games_steam.json").write_text(
        json.dumps({"fetched_at": "2026-01-01T00:00:00Z", "games": games}),
        encoding="utf-8",
    )
    return tmp_path


def _reload_enrich():
    for mod in ("enrichers.enrich_hltb", "clients.hltb_client"):
        sys.modules.pop(mod, None)
    import enrichers.enrich_hltb as enrich_hltb

    return enrich_hltb


def test_estimate_lookup_seconds() -> None:
    enrich = _reload_enrich()
    assert enrich.estimate_lookup_seconds(0) == 0
    assert enrich.estimate_lookup_seconds(10) == pytest.approx(10 * (0.15 + 7.5))


def test_circuit_breaker_stops_false_flood(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrich = _reload_enrich()
    monkeypatch.setattr(sys, "argv", ["enrich_hltb.py"])
    monkeypatch.setattr(enrich.time, "sleep", lambda _s: None)

    class EmptyClient:
        def lookup(self, _name: str):
            return None

    monkeypatch.setattr(enrich, "HltbClient", EmptyClient)
    code = enrich.main()
    assert code == 1
    mapping = json.loads((workspace / "cache" / "hltb_map.json").read_text(encoding="utf-8"))
    falses = [k for k, v in mapping.items() if k != "fetched_at" and v is False]
    assert len(falses) == enrich.CONSECUTIVE_EMPTY_ABORT
    assert len(falses) < 40


def test_catalog_checkpoint_mid_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrich = _reload_enrich()
    monkeypatch.setattr(sys, "argv", ["enrich_hltb.py"])
    monkeypatch.setattr(enrich.time, "sleep", lambda _s: None)
    flush_counts: list[int] = []

    real_flush = enrich._flush_catalog

    def counting_flush(rel, data, games):
        flush_counts.append(sum(1 for g in games if g.get("hltb_main_hours") is not None))
        return real_flush(rel, data, games)

    monkeypatch.setattr(enrich, "_flush_catalog", counting_flush)

    class HitClient:
        def lookup(self, name: str):
            return {
                "hltb_id": 1,
                "hltb_name": name,
                "hltb_main_hours": 5.0,
                "hltb_main_extra_hours": 6.0,
                "hltb_completionist_hours": 7.0,
                "hltb_match_confidence": 1.0,
            }

    monkeypatch.setattr(enrich, "HltbClient", HitClient)
    assert enrich.main() == 0
    # Mid-run flushes every 25 updates + final flush.
    assert any(c == 25 for c in flush_counts)
    assert flush_counts[-1] == 40
    written = json.loads((workspace / "games_steam.json").read_text(encoding="utf-8"))
    assert all(g.get("hltb_main_hours") == 5.0 for g in written["games"])
