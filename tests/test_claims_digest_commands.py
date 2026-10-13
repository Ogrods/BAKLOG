"""Digest issue publisher + owner checkbox commands (private-repo loop)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


digest = _load("claims_digest_issue")
cmds = _load("claims_commands")
autopilot = _load("claims_autopilot")


class FakeGh:
    def __init__(self, existing: int | None = None) -> None:
        self.existing = existing
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd, **kwargs):
        args = cmd[1:]
        self.calls.append((args, kwargs.get("input")))
        if args[:2] == ["issue", "list"]:
            rows = [{"number": self.existing}] if self.existing else []
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")
        if args[:2] == ["issue", "create"]:
            return subprocess.CompletedProcess(
                cmd, 0, "https://github.com/o/baklog-internal/issues/12\n", ""
            )
        if args[:2] == ["label", "create"]:
            return subprocess.CompletedProcess(cmd, 1, "", "label already exists")
        return subprocess.CompletedProcess(cmd, 0, "", "")


SUMMARY_CHANGED = {
    "changed": True,
    "diff": {
        "approved_added": ["epic-a"],
        "approved_removed": [],
        "dismissed_added": ["itad-a", "gamerpower-a"],
        "review_added": ["gamerpower-k"],
    },
}


def test_publish_creates_issue_and_mentions_owner() -> None:
    gh = FakeGh()
    result = digest.publish(
        repo="o/baklog-internal", digest_md="# body", summary=SUMMARY_CHANGED,
        mention="Owner", runner=gh,
    )
    assert result == {"number": 12, "created": True, "commented": True}
    comment_calls = [c for c in gh.calls if c[0][:2] == ["issue", "comment"]]
    [(args, body)] = comment_calls
    assert args[2] == "12"
    assert body.startswith("@Owner Claims autopilot: 1 auto-published, 2 dupes merged, 1 new for review.")
    assert "`gamerpower-k`" in body


def test_publish_edits_existing_issue_without_comment_when_unchanged() -> None:
    gh = FakeGh(existing=7)
    result = digest.publish(
        repo="o/r", digest_md="# body", summary={"changed": False, "diff": {}},
        mention="Owner", runner=gh,
    )
    assert result == {"number": 7, "created": False, "commented": False}
    edits = [c for c in gh.calls if c[0][:2] == ["issue", "edit"]]
    assert edits and edits[0][1] == "# body"
    assert not any(c[0][:2] == ["issue", "comment"] for c in gh.calls)


OLD = """\
- [ ] Remove: **A** <!-- cmd:remove:epic-a -->
- [ ] Not a dupe: kept **B** <!-- cmd:split:gamerpower-b,itad-b -->
- [ ] Approve: **K** <!-- cmd:approve:gamerpower-k -->
- [x] Approve: **Old** <!-- cmd:approve:gamerpower-old -->
"""


def test_newly_checked_only_counts_flips() -> None:
    new = OLD.replace("- [ ] Remove", "- [x] Remove").replace("- [ ] Not a dupe", "- [X] Not a dupe")
    assert cmds.newly_checked(OLD, new) == [
        ("remove", ["epic-a"]),
        ("split", ["gamerpower-b", "itad-b"]),
    ]


def test_bot_rewrite_with_all_boxes_clear_is_noop() -> None:
    assert cmds.newly_checked(OLD.replace("[x]", "[ ]"), OLD.replace("[x]", "[ ]")) == []


def test_injected_ids_are_rejected() -> None:
    new = "- [x] Remove <!-- cmd:remove:$(rm -rf /) -->\n"
    assert cmds.newly_checked("", new) == []


def test_apply_commands_updates_owner_doc() -> None:
    doc = {"ids": ["epic-a", "x"], "dismissed": ["gamerpower-k"], "blocked": [], "dupe_splits": []}
    updated, log = cmds.apply_commands(
        doc,
        [
            ("remove", ["epic-a"]),
            ("approve", ["gamerpower-k"]),
            ("split", ["itad-b", "gamerpower-b", "epic-b"]),
        ],
    )
    assert updated["ids"] == ["x", "gamerpower-k"]
    assert updated["blocked"] == ["epic-a"]
    assert "dismissed" not in updated
    assert updated["dupe_splits"] == [
        ["epic-b", "gamerpower-b"], ["epic-b", "itad-b"], ["gamerpower-b", "itad-b"]
    ]
    assert log == ["removed epic-a", "approved gamerpower-k", "split epic-b, gamerpower-b, itad-b"]


def _event(tmp_path: Path, sender: str, old: str, new: str) -> Path:
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps({
            "sender": {"login": sender},
            "changes": {"body": {"from": old}},
            "issue": {"body": new},
        }),
        encoding="utf-8",
    )
    return path


def test_main_ignores_non_owner(tmp_path: Path, capsys) -> None:
    approved = tmp_path / "a.json"
    approved.write_text('{"ids": []}', encoding="utf-8")
    new = OLD.replace("- [ ] Remove", "- [x] Remove")
    rc = cmds.main([
        "--event", str(_event(tmp_path, "stranger", OLD, new)),
        "--approved", str(approved), "--owner", "Owner",
    ])
    assert rc == 0
    assert "not the owner" in capsys.readouterr().out
    assert json.loads(approved.read_text(encoding="utf-8")) == {"ids": []}


def test_main_applies_owner_edit(tmp_path: Path, monkeypatch) -> None:
    approved = tmp_path / "a.json"
    approved.write_text('{"ids": ["epic-a"]}', encoding="utf-8")
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    new = OLD.replace("- [ ] Remove", "- [x] Remove")
    rc = cmds.main([
        "--event", str(_event(tmp_path, "owner", OLD, new)),
        "--approved", str(approved), "--owner", "Owner",
    ])
    assert rc == 0
    doc = json.loads(approved.read_text(encoding="utf-8"))
    assert doc == {"ids": [], "blocked": ["epic-a"]}
    text = out.read_text(encoding="utf-8")
    assert "applied=true" in text and "summary=removed epic-a" in text


def test_autopilot_digest_lines_round_trip_through_command_parser() -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "claims_inbox_2026_10.json").read_text("utf-8"))
    from datetime import UTC, datetime

    from shared.claims_policy import classify_inbox

    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    results = classify_inbox(fixture["items"], now=now)
    empty = {"approved_added": [], "approved_removed": [], "dismissed_added": [], "review_added": []}
    md = autopilot.render_digest(results, fixture["items"], empty, now=now)
    parsed = cmds._commands(md)
    actions = {a for a, _ in parsed}
    assert actions == {"remove", "approve", "split"}
    assert not any(parsed.values())
    ticked = md.replace("- [ ] Remove: **Out of Sight**", "- [x] Remove: **Out of Sight**")
    assert cmds.newly_checked(md, ticked) == [("remove", ["epic-out-of-sight-b96ca8"])]
