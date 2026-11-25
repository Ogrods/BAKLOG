#!/usr/bin/env python3
"""Audit manifest fetchers for base progress-communication coverage.

Flags scripts that look like multi-item jobs but lack HeartbeatTimer /
run_with_heartbeat / tick_progress. Pattern D (fast) keys can be allowlisted.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\audit_fetcher_progress.py
  .\\.venv\\Scripts\\python.exe scripts\\audit_fetcher_progress.py --fail-on-missing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fetchers" / "manifest.json"

# Keys whose scripts are short enough that Pattern D (phase only) is enough,
# or that are known to print per-item without HeartbeatTimer helpers.
PATTERN_D_ALLOWLIST = frozenset(
    {
        "claims",  # hosted JSON download - uses run_with_heartbeat after this audit
    }
)

PROGRESS_MARKERS = (
    "HeartbeatTimer",
    "run_with_heartbeat",
    "tick_progress",
    "tick_elapsed",
    "tick_progress_or_elapsed",
)

LOOPISH = re.compile(
    r"\b(for\s+\w+\s+in\s+|as_completed\s*\(|ThreadPoolExecutor\s*\()",
    re.MULTILINE,
)


def _load_manifest() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return list(data.get("fetchers") or [])


def _script_text(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def audit() -> list[dict]:
    rows: list[dict] = []
    for entry in _load_manifest():
        key = str(entry.get("key") or "")
        script = str(entry.get("script") or "")
        group = str(entry.get("group") or "")
        text = _script_text(script)
        has_progress = any(m in text for m in PROGRESS_MARKERS)
        loopish = bool(LOOPISH.search(text))
        allow = key in PATTERN_D_ALLOWLIST
        missing = loopish and not has_progress and not allow
        rows.append(
            {
                "key": key,
                "group": group,
                "script": script,
                "has_progress": has_progress,
                "loopish": loopish,
                "allowlisted": allow,
                "missing": missing,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit 1 when any non-allowlisted loopish script lacks progress helpers",
    )
    args = parser.parse_args()
    rows = audit()
    missing = [r for r in rows if r["missing"]]
    ok = [r for r in rows if r["has_progress"] or r["allowlisted"] or not r["loopish"]]

    print(f"Fetcher progress audit: {len(ok)} ok, {len(missing)} missing\n")
    for r in rows:
        if r["missing"]:
            flag = "MISSING"
        elif r["has_progress"]:
            flag = "ok"
        elif r["allowlisted"]:
            flag = "allow"
        else:
            flag = "fast?"
        print(f"  [{flag:7}] {r['key']:18} {r['group']:8} {r['script']}")

    if missing and args.fail_on_missing:
        print(f"\n{len(missing)} fetcher(s) need progress helpers.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
