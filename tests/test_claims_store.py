"""Private decision store: path resolution, autopilot merge order, build wiring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import fetchers.build_free_claims as bfc
from shared import claims_paths
from shared.claims_decisions import load_auto_decisions, merge_decisions, scoped_match_keys


def _make_internal(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "steam-backlog"
    repo.mkdir()
    claims = tmp_path / "baklog-internal" / "claims"
    claims.mkdir(parents=True)
    return repo, claims


def test_resolve_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "x.json"
    monkeypatch.setenv(claims_paths.APPROVED_ENV, str(target))
    assert claims_paths.resolve_approved_path(tmp_path) == target


def test_resolve_uses_sibling_internal_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(claims_paths.INTERNAL_REPO_ENV, raising=False)
    repo, claims = _make_internal(tmp_path)
    assert claims_paths.resolve_approved_path(repo) == claims / "free_claims.approved.json"
    assert claims_paths.resolve_auto_decisions_path(repo) == claims / "auto_decisions.json"


def test_resolve_falls_back_to_curated(tmp_path: Path) -> None:
    default = tmp_path / "curated" / "free_claims.approved.json"
    assert claims_paths.resolve_approved_path(tmp_path, default) == default
    assert claims_paths.resolve_auto_decisions_path(tmp_path) is None


def test_internal_repo_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "elsewhere"
    (other / "claims").mkdir(parents=True)
    monkeypatch.setenv(claims_paths.INTERNAL_REPO_ENV, str(other))
    assert claims_paths.resolve_approved_path(tmp_path) == other / "claims" / "free_claims.approved.json"


def test_load_auto_decisions_tolerates_missing_and_bad(tmp_path: Path) -> None:
    assert load_auto_decisions(None)["approve"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert load_auto_decisions(bad)["dismiss"] == []


ITEMS = [
    {"id": "epic-a", "source": "epic", "title": "A"},
    {"id": "itad-a", "source": "itad", "title": "A on Steam"},
    {"id": "epic-b", "source": "epic", "title": "B"},
    {"id": "epic-c", "source": "epic", "title": "C"},
]


def test_owner_dismissal_beats_auto_approve() -> None:
    merged = merge_decisions(
        owner_approved=set(),
        owner_dismissed={"epic-b"},
        auto={"approve": ["epic-a", "epic-b"], "dismiss": []},
        auto_items=ITEMS,
    )
    assert merged.approved_ids == {"epic-a"}
    assert merged.auto_approved == {"epic-a"}


def test_owner_key_dismissal_beats_auto_approve() -> None:
    merged = merge_decisions(
        owner_approved=set(),
        owner_dismissed=set(),
        auto={"approve": ["epic-c"]},
        auto_items=ITEMS,
        owner_dismissed_item_ids={"epic-c"},
    )
    assert merged.approved_ids == set()


def test_owner_approval_beats_auto_dismiss() -> None:
    merged = merge_decisions(
        owner_approved={"itad-a"},
        owner_dismissed=set(),
        auto={"dismiss": ["itad-a"]},
        auto_items=ITEMS,
    )
    assert "itad-a" in merged.approved_ids
    assert "itad-a" not in merged.dismissed_ids


def test_scoped_match_key_dismisses_loser_not_winner() -> None:
    loser = ITEMS[1]
    keys = sorted(k for k in scoped_match_keys(loser) if k.startswith("itad|title:"))
    churned = {"id": "itad-new", "source": "itad", "title": "A on Steam"}
    merged = merge_decisions(
        owner_approved=set(),
        owner_dismissed=set(),
        auto={"approve": ["epic-a"], "dismissed_match_keys": keys},
        auto_items=[ITEMS[0], churned],
    )
    assert "itad-new" in merged.dismissed_ids
    assert "epic-a" in merged.approved_ids
    assert "epic-a" not in merged.dismissed_ids


def _setup_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved: dict) -> tuple[Path, Path]:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "out.json"
    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "epic-owner", "source": "epic", "store": "epic", "title": "Owner Pick",
                     "claim_url": "https://store.epicgames.com/p/owner"},
                    {"id": "epic-auto", "source": "epic", "store": "epic", "title": "Auto Pick",
                     "claim_url": "https://store.epicgames.com/p/auto"},
                    {"id": "epic-vetoed", "source": "epic", "store": "epic", "title": "Vetoed",
                     "claim_url": "https://store.epicgames.com/p/vetoed"},
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            k: raw[k] for k in ("id", "store", "title", "claim_url")
        },
    )
    return approved_path, output_path


def test_build_merges_auto_decisions_under_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approved_path, output_path = _setup_build(
        tmp_path, monkeypatch, {"ids": ["epic-owner"], "dismissed": ["epic-vetoed"]}
    )
    auto_path = tmp_path / "auto_decisions.json"
    auto_path.write_text(
        json.dumps({"approve": ["epic-auto", "epic-vetoed"], "dismiss": ["epic-owner"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv", ["build_free_claims.py", "--no-profile", "--auto-decisions", str(auto_path)]
    )
    assert bfc.main() == 0
    ids = {it["id"] for it in json.loads(output_path.read_text(encoding="utf-8"))["items"]}
    assert ids == {"epic-owner", "epic-auto"}
    saved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert saved["ids"] == ["epic-owner"]


def test_build_reads_approved_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, output_path = _setup_build(tmp_path, monkeypatch, {"ids": []})
    alt = tmp_path / "alt-approved.json"
    alt.write_text(json.dumps({"ids": ["epic-auto"]}), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["build_free_claims.py", "--no-profile", "--approved", str(alt)]
    )
    assert bfc.main() == 0
    ids = {it["id"] for it in json.loads(output_path.read_text(encoding="utf-8"))["items"]}
    assert ids == {"epic-auto"}
