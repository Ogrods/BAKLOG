#!/usr/bin/env python3
"""Stable fingerprint + diff for free-claims feed items (Phase 2 PR gate).

Ignores stamp/enrich churn so rebuilds without claimable changes do not open a PR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Lean fields users care about for "did claimables change?"
FINGERPRINT_FIELDS = (
    "id",
    "store",
    "title",
    "claim_url",
    "claim_urls",
    "ends_at",
    "premium_only",
    "source",
)


def _norm_value(key: str, raw: Any) -> Any:
    if key == "premium_only":
        return True if raw is True else False
    if key == "claim_urls":
        if not isinstance(raw, dict):
            return None
        return {str(k): str(v or "").strip() for k, v in sorted(raw.items()) if str(v or "").strip()}
    if raw is None:
        return None
    if isinstance(raw, (int, float, bool)):
        return raw
    text = str(raw).strip()
    return text or None


def item_fingerprint(item: dict) -> tuple[Any, ...]:
    item_id = str(item.get("id") or "").strip()
    parts: list[Any] = [item_id]
    for key in FINGERPRINT_FIELDS:
        if key == "id":
            continue
        parts.append(_norm_value(key, item.get(key)))
    return tuple(parts)


def fingerprint_items(items: list[dict]) -> list[tuple[Any, ...]]:
    fps = [item_fingerprint(row) for row in items if isinstance(row, dict) and str(row.get("id") or "").strip()]
    return sorted(fps, key=lambda t: t[0] or "")


def load_items(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"feed must be an object: {path}")
    items = doc.get("items") or []
    if not isinstance(items, list):
        raise ValueError(f"items must be a list: {path}")
    return [row for row in items if isinstance(row, dict)]


def diff_fingerprints(
    before: list[tuple[Any, ...]],
    after: list[tuple[Any, ...]],
) -> dict[str, list[str]]:
    before_by_id = {str(fp[0]): fp for fp in before if fp and fp[0]}
    after_by_id = {str(fp[0]): fp for fp in after if fp and fp[0]}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    changed = sorted(
        item_id
        for item_id in (before_ids & after_ids)
        if before_by_id[item_id] != after_by_id[item_id]
    )
    return {"added": added, "removed": removed, "changed": changed}


def changed(diff: dict[str, list[str]]) -> bool:
    return bool(diff["added"] or diff["removed"] or diff["changed"])


def format_diff_markdown(diff: dict[str, list[str]], *, limit: int = 40) -> str:
    lines = [
        "## Free-claims fingerprint diff",
        "",
        f"- Added: **{len(diff['added'])}**",
        f"- Removed: **{len(diff['removed'])}**",
        f"- Changed: **{len(diff['changed'])}**",
        "",
    ]
    for label, key in (("Added", "added"), ("Removed", "removed"), ("Changed", "changed")):
        ids = diff[key]
        lines.append(f"### {label}")
        lines.append("")
        if not ids:
            lines.append("- (none)")
        else:
            for item_id in ids[:limit]:
                lines.append(f"- `{item_id}`")
            if len(ids) > limit:
                lines.append(f"- … and {len(ids) - limit} more")
        lines.append("")
    lines.append("_New scrape candidates are not auto-approved; this PR only refreshes previously published ids._")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True, help="Landing feed before rebuild")
    parser.add_argument("--after", type=Path, required=True, help="Landing feed after rebuild")
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to write diff JSON",
    )
    args = parser.parse_args(argv)

    try:
        before_fp = fingerprint_items(load_items(args.before))
        after_fp = fingerprint_items(load_items(args.after))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    diff = diff_fingerprints(before_fp, after_fp)
    if args.json_out:
        args.json_out.write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")

    md = format_diff_markdown(diff)
    print(md, end="")
    summary = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)

    if not changed(diff):
        print("No claimable fingerprint changes — skip PR.", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
