#!/usr/bin/env python3
"""Synthesize ephemeral free_claims.approved.json from committed landing feed.

Used by Phase 2 CI so rebuilds keep previously published ids (and premium_only)
without committing maintainer approved.json. Never commit the output file.

Also synthesizes field_overrides / store_overrides when landing differs from
auto so cron refresh does not wipe maintainer title/URL/ends_at edits baked
into the published feed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING_PATH = ROOT / "web" / "free-claims.json"
AUTO_PATH = ROOT / "curated" / "free_claims.auto.json"
APPROVED_OUT = ROOT / "curated" / "free_claims.approved.json"

_FIELD_OVERRIDE_KEYS = ("title", "claim_url", "ends_at", "claim_urls")


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


def _norm_scalar(value: object) -> str:
    return str(value or "").strip()


def _field_overrides_from_landing(
    landing_by_id: dict[str, dict],
    auto_by_id: dict[str, dict],
) -> dict[str, dict]:
    """Preserve landing title/URL/ends_at/claim_urls when they differ from auto."""
    field_overrides: dict[str, dict] = {}
    for item_id, land in landing_by_id.items():
        auto = auto_by_id.get(item_id)
        if not auto:
            continue
        cleaned: dict = {}
        for key in ("title", "claim_url", "ends_at"):
            land_v = land.get(key)
            if land_v is None or (isinstance(land_v, str) and not str(land_v).strip()):
                continue
            if _norm_scalar(land_v) != _norm_scalar(auto.get(key)):
                cleaned[key] = land_v
        land_urls = land.get("claim_urls") if isinstance(land.get("claim_urls"), dict) else {}
        auto_urls = auto.get("claim_urls") if isinstance(auto.get("claim_urls"), dict) else {}
        if land_urls and land_urls != auto_urls:
            cleaned["claim_urls"] = land_urls
        if cleaned:
            field_overrides[item_id] = cleaned
    return field_overrides


def synthesize_approved(
    landing_items: list[dict],
    *,
    auto_items: list[dict] | None = None,
) -> dict:
    """Build approved payload from landing rows (+ optional overrides vs auto)."""
    ids: list[str] = []
    premium_only_ids: list[str] = []
    landing_by_id = _id_map(landing_items)
    for item_id, row in sorted(landing_by_id.items()):
        ids.append(item_id)
        if row.get("premium_only") is True:
            premium_only_ids.append(item_id)

    store_overrides: dict[str, str] = {}
    field_overrides: dict[str, dict] = {}
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
        field_overrides = _field_overrides_from_landing(landing_by_id, auto_by_id)

    out: dict = {"ids": ids}
    if premium_only_ids:
        out["premium_only_ids"] = premium_only_ids
    if store_overrides:
        out["store_overrides"] = store_overrides
    if field_overrides:
        out["field_overrides"] = field_overrides
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--landing", type=Path, default=LANDING_PATH)
    parser.add_argument("--auto", type=Path, default=AUTO_PATH)
    parser.add_argument("--output", type=Path, default=APPROVED_OUT)
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="Skip reading auto feed (no store/field overrides).",
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
        f"{len(payload.get('store_overrides') or {})} store_override(s), "
        f"{len(payload.get('field_overrides') or {})} field_override(s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
