#!/usr/bin/env python3
"""Apply prune-only removals from a post-build approved.json onto the pre-build copy.

CI may rekey approvals in the workspace; this script never persists additions or
renames. It only removes ids (and matching overrides) that disappeared from the
after file relative to before. Exit codes: 0 wrote prunes, 3 nothing to prune,
1 unsafe (after gained ids) or I/O error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise SystemExit(f"{path} is not a JSON object")
    return doc


def _id_list(doc: dict) -> list[str]:
    raw = doc.get("ids") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def apply_prune_only(*, before: dict, after: dict) -> tuple[dict, list[str]]:
    before_ids = _id_list(before)
    after_ids = set(_id_list(after))
    before_set = set(before_ids)
    added = sorted(after_ids - before_set)
    if added:
        raise SystemExit(
            "refusing to persist approved.json: after file gained id(s) "
            f"{', '.join(added)} (rekey/additions are owner-owned)"
        )
    removed = [aid for aid in before_ids if aid not in after_ids]
    if not removed:
        return before, []
    removed_set = set(removed)
    out = json.loads(json.dumps(before))  # deep-ish copy via JSON
    out["ids"] = [aid for aid in before_ids if aid not in removed_set]
    for key in ("store_overrides", "field_overrides"):
        mapping = out.get(key)
        if isinstance(mapping, dict):
            out[key] = {
                k: v for k, v in mapping.items() if str(k).strip() not in removed_set
            }
            if not out[key]:
                out.pop(key, None)
    premium = out.get("premium_only_ids")
    if isinstance(premium, list):
        out["premium_only_ids"] = [
            str(x).strip()
            for x in premium
            if str(x).strip() and str(x).strip() not in removed_set
        ]
        if not out["premium_only_ids"]:
            out.pop("premium_only_ids", None)
    return out, removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    before = _load(args.before)
    after = _load(args.after)
    try:
        pruned, removed = apply_prune_only(before=before, after=after)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not removed:
        print("No approved id prunes to persist.")
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pruned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Persisting prune of {len(removed)} approved id(s): {', '.join(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
