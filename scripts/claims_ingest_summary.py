#!/usr/bin/env python3
"""Summarize claim-source ingest for GitHub Actions (Phase 1 cron).

Compares curated/free_claims.auto.json to landing/free-claims.json and checks
live baklog.app feed age. Soft-warns on stale live feed (exit 0). Hard-fails only
when required local files are unreadable after a successful fetch.

Public-safe output only: ids, titles, stores, ages. No secrets, no approved.json.
No public ::notice::/::warning:: annotations (summary text only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
DEFAULT_SKEW_DAYS = 1.0
SAMPLE_LIMIT = 25
_WS_RE = re.compile(r"\s+")


def sanitize_title(raw: object) -> str:
    """Collapse whitespace and strip backticks so markdown samples stay readable."""
    text = _WS_RE.sub(" ", str(raw or "").replace("`", "'")).strip()
    return text or "(no title)"


def _load_doc(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"missing feed: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"feed must be an object: {path}")
    return doc


def _load_items(path: Path) -> list[dict]:
    doc = _load_doc(path)
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
        title = sanitize_title(row.get("title"))
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


def _fmt_ts(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def fetch_live_doc(url: str) -> tuple[dict | None, str | None]:
    """Return (payload, error_message)."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed HTTPS URL
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return None, f"could not fetch live feed ({exc})"
    if not isinstance(payload, dict):
        return None, "live feed is not a JSON object"
    return payload, None


def check_live_age(url: str, *, max_age_days: float) -> tuple[str, bool, datetime | None]:
    """Return (summary line, stale, live_generated_at)."""
    payload, err = fetch_live_doc(url)
    if err or payload is None:
        return (f"WARN: {err}", False, None)

    generated = _parse_generated_at(payload.get("generated_at"))
    if generated is None:
        return ("WARN: live feed has no parseable generated_at", False, None)

    age_days = (datetime.now(UTC) - generated).total_seconds() / 86400.0
    item_count = len(payload.get("items") or []) if isinstance(payload.get("items"), list) else "?"
    line = (
        f"live generated_at={_fmt_ts(generated)} "
        f"age={age_days:.2f}d (limit={max_age_days:g}d) items={item_count}"
    )
    if age_days > max_age_days:
        return (f"WARN: {line} - refresh and republish", True, generated)
    return (f"OK: {line}", False, generated)


def landing_vs_live_skew_line(
    landing_generated: datetime | None,
    live_generated: datetime | None,
    *,
    skew_days: float = DEFAULT_SKEW_DAYS,
) -> str | None:
    """Return a summary line when committed landing and live clocks diverge."""
    if landing_generated is None or live_generated is None:
        return None
    delta_days = abs((landing_generated - live_generated).total_seconds()) / 86400.0
    if delta_days <= skew_days:
        return (
            f"OK: landing vs live skew={delta_days:.2f}d "
            f"(landing={_fmt_ts(landing_generated)}, live={_fmt_ts(live_generated)})"
        )
    return (
        f"WARN: landing vs live skew={delta_days:.2f}d "
        f"(limit={skew_days:g}d; landing={_fmt_ts(landing_generated)}, "
        f"live={_fmt_ts(live_generated)}) - committed feed and baklog.app differ"
    )


def build_markdown(
    *,
    auto_items: list[dict],
    landing_items: list[dict],
    live_line: str,
    live_stale: bool,
    skew_line: str | None = None,
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

    if skew_line:
        lines.extend(["### Landing vs live skew", "", skew_line, ""])

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
    parser.add_argument("--skew-days", type=float, default=DEFAULT_SKEW_DAYS)
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip live baklog.app age check (tests / offline).",
    )
    args = parser.parse_args(argv)

    try:
        landing_doc = _load_doc(args.landing)
        landing_items = [
            row for row in (landing_doc.get("items") or []) if isinstance(row, dict)
        ]
        if not isinstance(landing_doc.get("items") or [], list):
            raise ValueError(f"items must be a list: {args.landing}")
        auto_items = _load_items(args.auto)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    landing_generated = _parse_generated_at(landing_doc.get("generated_at"))

    if args.skip_live:
        live_line, live_stale, live_generated = ("SKIP: live age check disabled", False, None)
        skew_line = None
    else:
        live_line, live_stale, live_generated = check_live_age(
            args.live_url, max_age_days=args.max_age_days
        )
        skew_line = landing_vs_live_skew_line(
            landing_generated,
            live_generated,
            skew_days=args.skew_days,
        )

    md = build_markdown(
        auto_items=auto_items,
        landing_items=landing_items,
        live_line=live_line,
        live_stale=live_stale,
        skew_line=skew_line,
    )
    _write_summary(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
