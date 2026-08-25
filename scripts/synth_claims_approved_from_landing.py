#!/usr/bin/env python3
"""Synthesize ephemeral free_claims.approved.json from committed landing feed.

Used by Phase 2 CI so rebuilds keep previously published ids (and premium_only)
without committing maintainer approved.json. Never commit the output file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING_PATH = ROOT / "landing" / "free-claims.json"
AUTO_PATH = ROOT / "curated" / "free_claims.auto.json"
APPROVED_OUT = ROOT / "curated" / "free_claims.approved.json"


def _load_items(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"missing feed: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"feed must be an object: {path}")
    items = doc.get("items") or []
    if not isinstance(items, list):
        raise ValueError(f"items must be a list: {path}")
    return [row for row in items if isinstance(row, dict)]


def _id_map(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in items:
        item_id = str(row.get("id") or "").strip()
        if item_id:
            out[item_id] = row
    return out


def synthesize_approved(
    landing_items: list[dict],
    *,
    auto_items: list[dict] | None = None,
) -> dict:
    """Build approved payload from landing rows (+ optional store overrides vs auto)."""
    ids: list[str] = []
    premium_only_ids: list[str] = []
    landing_by_id = _id_map(landing_items)
    for item_id, row in sorted(landing_by_id.items()):
        ids.append(item_id)
        if row.get("premium_only") is True:
            premium_only_ids.append(item_id)

    store_overrides: dict[str, str] = {}
    if auto_items:
        auto_by_id = _id_map(auto_items)
        for item_id, land in landing_by_id.items():
            auto = auto_by_id.get(item_id)
            if not auto:
                continue
            land_store = str(land.get("store") or "").strip().lower()
            auto_store = str(auto.get("store") or "").strip().lower()
            if land_store and auto_store and land_store != auto_store:
                store_overrides[item_id] = land_store

    out: dict = {"ids": ids}
    if premium_only_ids:
        out["premium_only_ids"] = premium_only_ids
    if store_overrides:
        out["store_overrides"] = store_overrides
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--landing", type=Path, default=LANDING_PATH)
    parser.add_argument("--auto", type=Path, default=AUTO_PATH)
    parser.add_argument("--output", type=Path, default=APPROVED_OUT)
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="Skip reading auto feed (no store_overrides).",
    )
    args = parser.parse_args(argv)

    try:
        landing_items = _load_items(args.landing)
        auto_items: list[dict] | None = None
        if not args.no_auto and args.auto.is_file():
            auto_items = _load_items(args.auto)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = synthesize_approved(landing_items, auto_items=auto_items)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.output} with {len(payload.get('ids') or [])} id(s), "
        f"{len(payload.get('premium_only_ids') or [])} premium_only, "
        f"{len(payload.get('store_overrides') or {})} store_override(s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
