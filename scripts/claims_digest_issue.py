#!/usr/bin/env python3
"""Post the claims autopilot digest to a sticky issue in the private repo.

The issue body is replaced with the latest digest (checkbox commands reset each
run). When the autopilot reports changes, a short comment @mentions the owner
so GitHub sends a notification.

Uses the ``gh`` CLI; ``GH_TOKEN`` must be able to read/write issues on ``--repo``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claims_md import md_label  # noqa: E402

LABEL = "claims-digest"
TITLE = "Free claims autopilot"

Runner = Callable[..., subprocess.CompletedProcess]


def _gh(runner: Runner, *args: str, input_text: str | None = None) -> str:
    proc = runner(
        ["gh", *args],
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def find_issue(runner: Runner, repo: str) -> int | None:
    out = _gh(
        runner, "issue", "list", "--repo", repo, "--label", LABEL, "--state", "open",
        "--json", "number", "--limit", "1",
    )
    rows = json.loads(out or "[]")
    return int(rows[0]["number"]) if rows else None


def ensure_label(runner: Runner, repo: str) -> None:
    try:
        _gh(
            runner, "label", "create", LABEL, "--repo", repo, "--color", "B60205",
            "--description", "Claims autopilot digest (commands via checkboxes)",
        )
    except RuntimeError as exc:
        if "already exists" not in str(exc):
            raise


def change_comment(summary: dict, mention: str | None) -> str | None:
    diff = summary.get("diff") or {}
    titles = summary.get("titles") if isinstance(summary.get("titles"), dict) else {}
    parts = []
    if diff.get("approved_added"):
        parts.append(f"{len(diff['approved_added'])} auto-published")
    if diff.get("approved_removed"):
        parts.append(f"{len(diff['approved_removed'])} no longer auto-published")
    if diff.get("dismissed_added"):
        parts.append(f"{len(diff['dismissed_added'])} dupes merged")
    if diff.get("review_added"):
        parts.append(f"{len(diff['review_added'])} new for review")
    if not parts:
        return None
    who = f"@{mention} " if mention else ""
    lines = [f"{who}Claims autopilot: " + ", ".join(parts) + "."]
    for key, label in (
        ("approved_added", "Auto-published"),
        ("review_added", "Needs review"),
        ("dismissed_added", "Dupes hidden"),
    ):
        ids = diff.get(key) or []
        if ids:
            shown = ", ".join(md_label(titles.get(i), i) for i in ids[:15])
            more = f" and {len(ids) - 15} more" if len(ids) > 15 else ""
            lines.append(f"- {label}: {shown}{more}")
    lines.append("")
    lines.append("Tick a box in the issue body to remove, approve, or split.")
    return "\n".join(lines)


def publish(
    *,
    repo: str,
    digest_md: str,
    summary: dict,
    mention: str | None,
    runner: Runner = subprocess.run,
) -> dict:
    number = find_issue(runner, repo)
    if number is None:
        ensure_label(runner, repo)
        url = _gh(
            runner, "issue", "create", "--repo", repo, "--title", TITLE, "--label", LABEL,
            "--body-file", "-", input_text=digest_md,
        ).strip()
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
        created = True
    else:
        _gh(
            runner, "issue", "edit", str(number), "--repo", repo, "--body-file", "-",
            input_text=digest_md,
        )
        created = False
    comment = change_comment(summary, mention) if summary.get("changed") else None
    if comment:
        _gh(
            runner, "issue", "comment", str(number), "--repo", repo, "--body-file", "-",
            input_text=comment,
        )
    return {"number": number, "created": created, "commented": bool(comment)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--digest-md", type=Path, required=True)
    parser.add_argument("--digest-json", type=Path, required=True)
    parser.add_argument("--mention", default=None, help="GitHub login to @mention on changes")
    args = parser.parse_args(argv)
    digest = args.digest_md.read_text(encoding="utf-8")
    summary = json.loads(args.digest_json.read_text(encoding="utf-8"))
    try:
        result = publish(repo=args.repo, digest_md=digest, summary=summary, mention=args.mention)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
