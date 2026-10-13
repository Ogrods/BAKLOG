"""scripts/claims_autopilot.py: decisions, digest, auto-merge gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "claims_inbox_2026_10.json"
NOW = "2026-10-12T12:00:00Z"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "claims_autopilot", ROOT / "scripts" / "claims_autopilot.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ap = _load_module()


@pytest.fixture()
def paths(tmp_path: Path) -> dict[str, Path]:
    inbox = json.loads(FIXTURE.read_text(encoding="utf-8"))
    auto = tmp_path / "free_claims.auto.json"
    auto.write_text(json.dumps({"items": inbox["items"]}), encoding="utf-8")
    approved = tmp_path / "free_claims.approved.json"
    approved.write_text(json.dumps({"ids": ["gamerpower-3328"]}), encoding="utf-8")
    return {
        "auto": auto,
        "approved": approved,
        "decisions": tmp_path / "auto_decisions.json",
        "md": tmp_path / "digest.md",
        "json": tmp_path / "digest.json",
    }


def _run(paths: dict[str, Path], *extra: str, now: str = NOW) -> int:
    return ap.main(
        [
            "run",
            "--auto", str(paths["auto"]),
            "--approved", str(paths["approved"]),
            "--decisions", str(paths["decisions"]),
            "--digest-md", str(paths["md"]),
            "--digest-json", str(paths["json"]),
            "--now", now,
            *extra,
        ]
    )


def test_run_writes_decisions_and_digest(paths, monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert _run(paths) == 0
    doc = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    assert doc["approve"] == sorted(
        ["epic-out-of-sight-b96ca8", "epic-terrascape-2b12b1", "gamerpower-3810", "gamerpower-3809"]
    )
    assert "itad-123db3b7378b" in doc["dismiss"]  # Best Plumber ITAD copy, owner kept GP row
    assert len(doc["dismiss"]) == 12
    assert doc["decisions"]["gamerpower-3716"]["action"] == "review"
    assert "gamerpower-3328" not in doc["decisions"]  # owner decision, untouched
    assert "changed=true" in out.read_text(encoding="utf-8")

    md = paths["md"].read_text(encoding="utf-8")
    assert md.startswith(ap.DIGEST_MARKER)
    assert "<!-- cmd:remove:epic-out-of-sight-b96ca8 -->" in md
    # Undated and no last_seen in the fixture, so approving also sets an end date.
    assert "<!-- cmd:approve-stale:gamerpower-3716 -->" in md
    assert "<!-- cmd:split:epic-out-of-sight-b96ca8,gamerpower-3806,itad-fadc757d9c68 -->" in md \
        or "<!-- cmd:split:epic-out-of-sight-b96ca8,itad-fadc757d9c68,gamerpower-3806 -->" in md
    summary = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert summary["counts"]["groups"] == 10


def test_second_run_is_unchanged(paths, monkeypatch, tmp_path: Path) -> None:
    assert _run(paths) == 0
    first = paths["decisions"].read_text(encoding="utf-8")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert _run(paths, now="2026-10-12T13:00:00Z") == 0
    assert "changed=false" in out.read_text(encoding="utf-8")
    assert paths["decisions"].read_text(encoding="utf-8") == first


def test_dismissed_match_keys_never_cover_keeper(paths) -> None:
    assert _run(paths) == 0
    doc = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    keys = set(doc["dismissed_match_keys"])
    assert "itad|title:out of sight" in keys
    assert not any(k.startswith("epic|") for k in keys)


def test_owner_dismissed_keys_block_auto_publish(paths) -> None:
    paths["approved"].write_text(
        json.dumps({"ids": [], "dismissed_keys": ["pony island"]}), encoding="utf-8"
    )
    assert _run(paths) == 0
    doc = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    assert "gamerpower-3809" not in doc["approve"]


def test_dry_run_does_not_write_decisions(paths) -> None:
    assert _run(paths, "--dry-run") == 0
    assert not paths["decisions"].exists()
    assert paths["md"].is_file()


def test_owner_split_breaks_group(paths) -> None:
    paths["approved"].write_text(
        json.dumps({"ids": [], "dupe_splits": [["gamerpower-3313", "itad-b39ef7bfe392"]]}),
        encoding="utf-8",
    )
    assert _run(paths) == 0
    doc = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    assert "itad-b39ef7bfe392" not in doc["dismiss"]


def _feed(path: Path, ids: list[str]) -> Path:
    path.write_text(json.dumps({"items": [{"id": i} for i in ids]}), encoding="utf-8")
    return path


def test_verify_added_passes_when_every_add_is_vetted(tmp_path: Path) -> None:
    approved = tmp_path / "a.json"
    approved.write_text(json.dumps({"ids": ["owner-1"]}), encoding="utf-8")
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps({"approve": ["auto-1"]}), encoding="utf-8")
    rc = ap.main([
        "verify-added",
        "--before", str(_feed(tmp_path / "b.json", ["old"])),
        "--after", str(_feed(tmp_path / "c.json", ["old", "owner-1", "auto-1"])),
        "--approved", str(approved),
        "--decisions", str(decisions),
    ])
    assert rc == 0


def test_verify_added_flags_unvetted(tmp_path: Path, capsys) -> None:
    approved = tmp_path / "a.json"
    approved.write_text(json.dumps({"ids": []}), encoding="utf-8")
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps({"approve": []}), encoding="utf-8")
    rc = ap.main([
        "verify-added",
        "--before", str(_feed(tmp_path / "b.json", [])),
        "--after", str(_feed(tmp_path / "c.json", ["mystery"])),
        "--approved", str(approved),
        "--decisions", str(decisions),
    ])
    assert rc == 3
    assert "unvetted: mystery" in capsys.readouterr().out


def test_verify_added_trusts_manual_rows(tmp_path: Path) -> None:
    approved = tmp_path / "a.json"
    approved.write_text(json.dumps({"ids": []}), encoding="utf-8")
    decisions = tmp_path / "d.json"
    decisions.write_text("{}", encoding="utf-8")
    manual = _feed(tmp_path / "m.json", ["manual-x"])
    rc = ap.main([
        "verify-added",
        "--before", str(_feed(tmp_path / "b.json", [])),
        "--after", str(_feed(tmp_path / "c.json", ["manual-x"])),
        "--approved", str(approved),
        "--decisions", str(decisions),
        "--manual", str(manual),
    ])
    assert rc == 0


def _verify_links(tmp_path: Path, old: dict, new: dict) -> int:
    approved = tmp_path / "a.json"
    approved.write_text(json.dumps({"ids": []}), encoding="utf-8")
    decisions = tmp_path / "d.json"
    decisions.write_text("{}", encoding="utf-8")
    before = tmp_path / "b.json"
    before.write_text(json.dumps({"items": [{"id": "x", "title": "Game", **old}]}), encoding="utf-8")
    after = tmp_path / "c.json"
    after.write_text(json.dumps({"items": [{"id": "x", "title": "Game", **new}]}), encoding="utf-8")
    return ap.main([
        "verify-added",
        "--before", str(before),
        "--after", str(after),
        "--approved", str(approved),
        "--decisions", str(decisions),
    ])


def test_verify_added_holds_on_link_host_change(tmp_path: Path, capsys) -> None:
    rc = _verify_links(
        tmp_path,
        {"claim_url": "https://store.epicgames.com/p/game"},
        {"claim_url": "https://evil.example/p/game"},
    )
    assert rc == 3
    assert "link host changed: Game (x)" in capsys.readouterr().out


def test_verify_added_holds_on_new_host_in_claim_urls(tmp_path: Path) -> None:
    rc = _verify_links(
        tmp_path,
        {"claim_url": "https://store.steampowered.com/app/1"},
        {"claim_url": "https://store.steampowered.com/app/1", "claim_urls": {"epic": "https://other.example/x"}},
    )
    assert rc == 3


def test_verify_added_holds_on_ambiguous_link(tmp_path: Path) -> None:
    rc = _verify_links(
        tmp_path,
        {"claim_url": "https://store.epicgames.com/p/game"},
        {"claim_url": "https://evil.example\\@store.epicgames.com/p/game"},
    )
    assert rc == 3


def test_verify_added_holds_on_malformed_link(tmp_path: Path) -> None:
    rc = _verify_links(
        tmp_path,
        {"claim_url": "https://store.epicgames.com/p/game"},
        {"claim_url": "http://[evil"},
    )
    assert rc == 3


def test_verify_added_allows_same_host_path_change(tmp_path: Path) -> None:
    rc = _verify_links(
        tmp_path,
        {"claim_url": "https://www.gog.com/en/game/old"},
        {"claim_url": "https://gog.com/en/game/new?utm=1"},
    )
    assert rc == 0
