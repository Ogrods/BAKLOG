#!/usr/bin/env python3
"""Summarize claim-source ingest for GitHub Actions (Phase 1 cron).

Compares curated/free_claims.auto.json to landing/free-claims.json and checks
live baklog.app feed age. Soft-warns on stale live feed (exit 0). Hard-fails only
when required local files are unreadable after a successful fetch.

Public-safe output only: ids, titles, stores, ages. No secrets, no approved.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
AUTO_PATH = ROOT / "curated" / "free_claims.auto.json"
LANDING_PATH = ROOT / "landing" / "free-claims.json"
LIVE_URL = "https://baklog.app/free-claims.json"
USER_AGENT = "BAKLOG-claims-ingest-summary/1.0"
DEFAULT_MAX_AGE_DAYS = 7
SAMPLE_LIMIT = 25


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


def _source_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in items:
        src = str(row.get("source") or row.get("store") or "unknown").strip() or "unknown"
        counts[src] = counts.get(src, 0) + 1
    return dict(sorted(counts.items()))


def _sample_lines(ids: set[str], by_id: dict[str, dict], *, limit: int = SAMPLE_LIMIT) -> list[str]:
    lines: list[str] = []
    for item_id in sorted(ids)[:limit]:
        row = by_id.get(item_id) or {}
        title = str(row.get("title") or "").strip() or "(no title)"
        store = str(row.get("store") or row.get("source") or "").strip()
        suffix = f" [{store}]" if store else ""
        lines.append(f"- `{item_id}`{suffix}: {title}")
    remaining = len(ids) - limit
    if remaining > 0:
        lines.append(f"- … and {remaining} more")
    return lines


def _parse_generated_at(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def check_live_age(url: str, *, max_age_days: float) -> tuple[str, bool]:
    """Return (summary line, stale). Network errors are warnings, not failures."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed HTTPS URL
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return (f"WARN: could not fetch live feed ({exc})", False)

    if not isinstance(payload, dict):
        return ("WARN: live feed is not a JSON object", False)

    generated = _parse_generated_at(payload.get("generated_at"))
    if generated is None:
        return ("WARN: live feed has no parseable generated_at", False)

    age_days = (datetime.now(UTC) - generated).total_seconds() / 86400.0
    item_count = len(payload.get("items") or []) if isinstance(payload.get("items"), list) else "?"
    line = (
        f"live generated_at={generated.isoformat().replace('+00:00', 'Z')} "
        f"age={age_days:.2f}d (limit={max_age_days:g}d) items={item_count}"
    )
    if age_days > max_age_days:
        return (f"WARN: {line} - refresh and republish", True)
    return (f"OK: {line}", False)


def build_markdown(
    *,
    auto_items: list[dict],
    landing_items: list[dict],
    live_line: str,
    live_stale: bool,
) -> str:
    auto_by_id = _id_map(auto_items)
    land_by_id = _id_map(landing_items)
    auto_ids = set(auto_by_id)
    land_ids = set(land_by_id)
    new_ids = auto_ids - land_ids
    gone_ids = land_ids - auto_ids
    still_ids = auto_ids & land_ids

    lines = [
        "## Claims ingest summary",
        "",
        f"- Auto items: **{len(auto_items)}** (unique ids: {len(auto_ids)})",
        f"- Landing published ids: **{len(land_ids)}**",
        f"- Still in both: **{len(still_ids)}**",
        f"- New scrape candidates (not in landing): **{len(new_ids)}**",
        f"- Landing ids missing from scrape: **{len(gone_ids)}**",
        "",
        "### Auto counts by source",
        "",
    ]
    counts = _source_counts(auto_items)
    if counts:
        for src, n in counts.items():
            lines.append(f"- `{src}`: {n}")
    else:
        lines.append("- (none)")

    lines.extend(["", "### Live baklog.app age", "", live_line, ""])
    if live_stale:
        lines.append("_Soft warn only - job stays green. Publish when ready._")
        lines.append("")

    lines.extend(["### New scrape candidates (sample)", ""])
    if new_ids:
        lines.extend(_sample_lines(new_ids, auto_by_id))
    else:
        lines.append("- (none)")

    lines.extend(["", "### Landing ids not in this scrape (sample)", ""])
    if gone_ids:
        lines.extend(_sample_lines(gone_ids, land_by_id))
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "### Maintainer next steps",
            "",
            "1. Review new candidates in admin Claims (or local fetch + approved.json).",
            "2. `build_free_claims.py` → commit `landing/free-claims.json` + `curated/free_claims.fallback.json`.",
            "3. Push so Vercel updates baklog.app.",
            "",
            "_Phase 1: notify only. No auto-approve, no PR, no deploy hook._",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", type=Path, default=AUTO_PATH)
    parser.add_argument("--landing", type=Path, default=LANDING_PATH)
    parser.add_argument("--live-url", default=LIVE_URL)
    parser.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip live baklog.app age check (tests / offline).",
    )
    args = parser.parse_args(argv)

    try:
        auto_items = _load_items(args.auto)
        landing_items = _load_items(args.landing)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.skip_live:
        live_line, live_stale = ("SKIP: live age check disabled", False)
    else:
        live_line, live_stale = check_live_age(args.live_url, max_age_days=args.max_age_days)

    md = build_markdown(
        auto_items=auto_items,
        landing_items=landing_items,
        live_line=live_line,
        live_stale=live_stale,
    )
    _write_summary(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
