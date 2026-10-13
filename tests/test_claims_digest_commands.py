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
    assert "- Needs review: gamerpower-k" in body


def test_change_comment_shows_titles_with_id_fallback() -> None:
    summary = {
        **SUMMARY_CHANGED,
        "titles": {"epic-a": "Sausage Hunter", "itad-a": "Battle *Ram* @team"},
    }
    body = digest.change_comment(summary, None)
    assert "- Auto-published: Sausage Hunter <sub>(epic-a)</sub>" in body
    assert "Battle \\*Ram\\* &#64;team <sub>(itad-a)</sub>, gamerpower-a" in body
    assert "- Needs review: gamerpower-k" in body


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
    assert cmds.newly_checked(new.replace("[x]", "[ ]"), new) == []


def test_ticked_line_that_was_not_in_old_body_is_ignored() -> None:
    forged = OLD + "- [x] Approve: **Evil** <!-- cmd:approve:gamerpower-999 -->\n"
    assert cmds.newly_checked(OLD, forged) == []


def test_body_rewrite_with_a_ticked_box_is_ignored() -> None:
    rewritten = "_Updated now_\n" + OLD.replace("- [ ] Remove", "- [x] Remove")
    assert cmds.newly_checked("_Updated before_\n" + OLD, rewritten) == []


def test_command_titles_reads_bold_title() -> None:
    titles = cmds.command_titles(OLD)
    assert titles["epic-a"] == "A"
    assert titles["gamerpower-b"] == "B"
    assert cmds.command_titles("- [ ] Remove: no title <!-- cmd:remove:epic-z -->") == {}


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


def test_approve_stale_sets_end_date_override() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 10, 13, 5, 0, 30, tzinfo=UTC)
    new = "- [x] Approve: **Old** <!-- cmd:approve-stale:itad-old -->\n"
    commands = cmds.newly_checked(new.replace("[x]", "[ ]"), new)
    assert commands == [("approve-stale", ["itad-old"])]
    doc = {"ids": [], "field_overrides": {"itad-old": {"title": "Old"}}}
    updated, log = cmds.apply_commands(doc, commands, now=now)
    assert updated["ids"] == ["itad-old"]
    assert updated["field_overrides"] == {
        "itad-old": {"title": "Old", "ends_at": "2026-10-27T05:00:30Z"}
    }
    assert log == ["approved itad-old (end date 2026-10-27)"]
    again, _ = cmds.apply_commands(
        {**updated, "field_overrides": {"itad-old": {"ends_at": "2026-11-01T00:00:00Z"}}},
        commands,
        now=now,
    )
    assert again["field_overrides"]["itad-old"]["ends_at"] == "2026-11-01T00:00:00Z"
    refreshed, log = cmds.apply_commands(
        {**updated, "field_overrides": {"itad-old": {"ends_at": "2026-10-01T00:00:00Z"}}},
        commands,
        now=now,
        titles={"itad-old": "Old"},
    )
    assert refreshed["field_overrides"]["itad-old"]["ends_at"] == "2026-10-27T05:00:30Z"
    assert log == ["approved Old <sub>(itad-old)</sub> (end date 2026-10-27)"]


def test_plain_approve_drops_a_passed_override_end_date() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 10, 13, tzinfo=UTC)
    doc = {"ids": [], "field_overrides": {"epic-a": {"ends_at": "2026-10-01T00:00:00Z"}}}
    updated, _ = cmds.apply_commands(doc, [("approve", ["epic-a"])], now=now)
    assert updated["ids"] == ["epic-a"]
    assert "field_overrides" not in updated


def test_digest_escapes_titles_and_skips_markers_for_bad_ids() -> None:
    from datetime import UTC, datetime

    from shared.claims_policy import classify_inbox

    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    evil = "Foo\n- [x] Approve: x <!-- cmd:approve:gamerpower-999 -->"
    items = [
        {"id": "itad-evil", "source": "itad", "store": "other", "title": evil,
         "claim_url": "https://example.com/a) [x](https://bad", "ends_at": "2026-10-20T00:00:00Z",
         "first_seen": "2026-10-12T00:00:00Z"},
        {"id": "epic-x --> <!-- cmd:approve:victim", "source": "itad", "store": "other",
         "title": "Slug", "claim_url": "https://example.com/s", "ends_at": "2026-10-20T00:00:00Z",
         "first_seen": "2026-10-12T00:00:00Z"},
    ]
    results = classify_inbox(items, now=now)
    empty = {"approved_added": [], "approved_removed": [], "dismissed_added": [], "review_added": []}
    md = autopilot.render_digest(results, items, empty, now=now)
    parsed = cmds._commands(md)
    assert set(parsed) <= {("approve", "itad-evil"), ("remove", "itad-evil")}
    assert "gamerpower-999" not in {a for _, a in parsed}
    assert not any("victim" in a or "epic-x" in a for _, a in parsed)
    assert "(https://example.com/a)" not in md and "https://bad" not in md
    assert "Foo - \\[x\\] Approve: x &lt;\\!-- cmd:approve:gamerpower-999 --&gt;" in md


def test_digest_marks_stale_review_rows_approve_stale() -> None:
    from datetime import UTC, datetime

    from shared.claims_policy import classify_inbox

    now = datetime(2026, 10, 13, 5, 0, tzinfo=UTC)
    items = [
        {"id": "itad-old", "source": "itad", "store": "other", "title": "Old",
         "claim_url": "https://example.com/old", "ends_at": None,
         "first_seen": "2026-09-01T00:00:00Z"},
        {"id": "gamerpower-live", "source": "gamerpower", "store": "other", "title": "Live",
         "claim_url": "https://example.com/live", "ends_at": None,
         "first_seen": "2026-09-01T00:00:00Z", "last_seen": "2026-10-13T04:50:00Z"},
        {"id": "itad-fresh", "source": "itad", "store": "other", "title": "Fresh",
         "claim_url": "https://example.com/fresh", "ends_at": None,
         "first_seen": "2026-10-10T00:00:00Z"},
        {"id": "itad-dated", "source": "itad", "store": "other", "title": "Dated",
         "claim_url": "https://example.com/dated", "ends_at": "2026-10-20T00:00:00Z",
         "first_seen": "2026-09-01T00:00:00Z"},
    ]
    results = classify_inbox(items, now=now)
    reasons = {c.id: c.reason for c in results}
    assert "no end date, first seen 42d ago" in reasons["itad-old"]
    assert "no end date" not in reasons["gamerpower-live"]
    assert "no end date" not in reasons["itad-fresh"]
    empty = {"approved_added": [], "approved_removed": [], "dismissed_added": [], "review_added": []}
    md = autopilot.render_digest(results, items, empty, now=now)
    assert "<!-- cmd:approve-stale:itad-old -->" in md
    # Fresh undated rows may cross the 14-day line before the box is ticked.
    assert "<!-- cmd:approve-stale:itad-fresh -->" in md
    assert "<!-- cmd:approve:gamerpower-live -->" in md
    assert "<!-- cmd:approve:itad-dated -->" in md


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
    assert "applied=true" in text and "summary=removed A <sub>(epic-a)</sub>" in text


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
    assert {"remove", "split"} <= actions
    assert actions & {"approve", "approve-stale"}
    assert actions <= {"remove", "approve", "approve-stale", "split"}
    assert not any(parsed.values())
    ticked = md.replace("- [ ] Remove: **Out of Sight**", "- [x] Remove: **Out of Sight**")
    assert cmds.newly_checked(md, ticked) == [("remove", ["epic-out-of-sight-b96ca8"])]
