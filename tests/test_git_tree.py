"""Tests for scripts/git_tree.py snapshot collectors and rendering."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "git_tree.py"
_spec = importlib.util.spec_from_file_location("git_tree", _MODULE_PATH)
assert _spec and _spec.loader
git_tree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(git_tree)


def test_parse_ahead_behind_basic():
    assert git_tree.parse_ahead_behind("3\t5") == {"behind": 3, "ahead": 5}
    assert git_tree.parse_ahead_behind("0 0") == {"behind": 0, "ahead": 0}


def test_parse_ahead_behind_malformed():
    assert git_tree.parse_ahead_behind("") == {"behind": 0, "ahead": 0}
    assert git_tree.parse_ahead_behind("nope") == {"behind": 0, "ahead": 0}
    assert git_tree.parse_ahead_behind("a\tb") == {"behind": 0, "ahead": 0}


def test_parse_branch_row_full():
    line = "\x1f".join(
        ["feature/x", "abc1234", "origin/feature/x", "2026-06-10 10:00:00 -0700", "Do a thing", "Dan"]
    )
    row = git_tree.parse_branch_row(line)
    assert row == {
        "name": "feature/x",
        "sha": "abc1234",
        "upstream": "origin/feature/x",
        "date": "2026-06-10 10:00:00 -0700",
        "subject": "Do a thing",
        "author": "Dan",
    }


def test_parse_branch_row_missing_fields():
    # No upstream, no subject, no author -> blanks, still parses.
    line = "\x1f".join(["solo", "def5678", "", "2026-06-10 10:00:00 -0700"])
    row = git_tree.parse_branch_row(line)
    assert row is not None
    assert row["name"] == "solo"
    assert row["upstream"] == ""
    assert row["subject"] == ""
    assert row["author"] == ""


def test_parse_branch_row_blank_returns_none():
    assert git_tree.parse_branch_row("") is None
    assert git_tree.parse_branch_row("\x1fabc\x1f") is None  # empty name


def test_collect_prs_gh_absent(monkeypatch):
    monkeypatch.setattr(git_tree.shutil, "which", lambda _name: None)
    result = git_tree.collect_prs()
    assert result == {"available": False, "items": []}


def test_render_fragment_escapes_script_close(monkeypatch):
    # A subject containing </script> must not break out of the JSON block.
    snapshot = {
        "generated_at": "2026-06-10T22:00:00-07:00",
        "repo": "steam-backlog",
        "base": "main",
        "current": "main",
        "dirty": False,
        "dirty_count": 0,
        "branches": [{"name": "main", "sha": "abc", "subject": "</script> hack", "date": "", "upstream": "", "ahead": 0, "behind": 0, "current": True}],
        "remotes": [],
        "commits": [],
        "graph_text": "",
        "prs": {"available": False, "items": []},
        "max_commits": 300,
    }
    fragment = git_tree.render_fragment(snapshot)
    assert "</script> hack" not in fragment
    assert "<\\/script>" in fragment
    # The embedded JSON is still valid once the escape is reversed.
    start = fragment.index('id="git-tree-data">') + len('id="git-tree-data">')
    end = fragment.index("</script>", start)
    payload = fragment[start:end].replace("<\\/", "</")
    parsed = json.loads(payload)
    assert parsed["repo"] == "steam-backlog"


def test_render_html_is_self_contained():
    snapshot = {
        "generated_at": "2026-06-10T22:00:00-07:00",
        "repo": "steam-backlog",
        "base": "main",
        "current": "main",
        "dirty": False,
        "dirty_count": 0,
        "branches": [],
        "remotes": [],
        "commits": [],
        "graph_text": "",
        "prs": {"available": True, "items": []},
        "max_commits": 300,
    }
    html = git_tree.render_html(snapshot)
    assert html.startswith("<!DOCTYPE html>")
    assert "git-tree-data" in html
    # No external asset loading (offline-safe): no CDN scripts/styles/images.
    # (The SVG XML namespace URL is a required constant, not a fetch.)
    assert "<script src=" not in html
    assert "<link " not in html
    assert "src=" not in html
    assert "cdn" not in html.lower()
    assert "https://" not in html
