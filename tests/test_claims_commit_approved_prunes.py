"""Unit tests for scripts/claims_commit_approved_prunes.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.claims_commit_approved_prunes import apply_prune_only
from scripts.claims_commit_approved_prunes import main as prune_main


def test_apply_prune_only_removes_ids_and_overrides() -> None:
    before = {
        "ids": ["keep", "drop"],
        "field_overrides": {"drop": {"title": "X"}, "keep": {"title": "Y"}},
        "premium_only_ids": ["drop", "keep"],
    }
    after = {"ids": ["keep"]}
    out, removed = apply_prune_only(before=before, after=after)
    assert removed == ["drop"]
    assert out["ids"] == ["keep"]
    assert out["field_overrides"] == {"keep": {"title": "Y"}}
    assert out["premium_only_ids"] == ["keep"]


def test_apply_prune_only_refuses_additions() -> None:
    before = {"ids": ["a"]}
    after = {"ids": ["a", "b"]}
    with pytest.raises(SystemExit, match="gained id"):
        apply_prune_only(before=before, after=after)


def test_cli_writes_prune_file(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    out = tmp_path / "out.json"
    before.write_text(json.dumps({"ids": ["a", "b"]}), encoding="utf-8")
    after.write_text(json.dumps({"ids": ["a"]}), encoding="utf-8")
    assert prune_main(["--before", str(before), "--after", str(after), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ids"] == ["a"]


def test_cli_exit_3_when_unchanged(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    out = tmp_path / "out.json"
    before.write_text(json.dumps({"ids": ["a"]}), encoding="utf-8")
    after.write_text(json.dumps({"ids": ["a"]}), encoding="utf-8")
    assert prune_main(["--before", str(before), "--after", str(after), "--out", str(out)]) == 3
    assert not out.exists()
