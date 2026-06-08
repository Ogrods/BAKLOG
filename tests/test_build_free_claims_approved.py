"""Tests for opt-in approved auto-claim filtering in build_free_claims.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import build_free_claims as bfc


def test_load_approved_ids_missing_file(tmp_path: Path) -> None:
    assert bfc._load_approved_ids(tmp_path / "missing.json") == set()


def test_load_approved_ids_reads_ids(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(json.dumps({"ids": ["epic-a", "gamerpower-1"]}), encoding="utf-8")
    assert bfc._load_approved_ids(path) == {"epic-a", "gamerpower-1"}


def test_load_approved_ids_ignores_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text("{not json", encoding="utf-8")
    assert bfc._load_approved_ids(path) == set()


def test_build_publishes_only_approved_auto_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-1",
                        "store": "steam",
                        "title": "Manual Always",
                        "claim_url": "https://store.steampowered.com/app/1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-approved",
                        "store": "epic",
                        "title": "Approved Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/approved",
                        "source": "epic",
                    },
                    {
                        "id": "gog-hidden",
                        "store": "gog",
                        "title": "Hidden GOG",
                        "claim_url": "https://www.gog.com/game/hidden",
                        "source": "gamerpower",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(json.dumps({"ids": ["epic-approved"]}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"manual-1", "epic-approved"}


def test_build_without_approved_file_publishes_manual_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-only",
                        "store": "steam",
                        "title": "Manual Only",
                        "claim_url": "https://store.steampowered.com/app/2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-unapproved",
                        "store": "epic",
                        "title": "Should Not Publish",
                        "claim_url": "https://store.epicgames.com/en-US/p/nope",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in built["items"]] == ["manual-only"]
