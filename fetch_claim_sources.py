#!/usr/bin/env python3
"""Fetch auto-discovered free claimable games from Epic, GamerPower, and ITAD RSS."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

from fetchers._base import refuse_empty_result
from fetchers._progress import RunStats, started
from shared.free_claims_sources import (
    EPIC_FREE_GAMES_URL,
    GAMERPOWER_ATTRIBUTION,
    GAMERPOWER_URL,
    ITAD_GIVEAWAYS_RSS,
    carry_claim_enrichment,
    dedup_claim_items_by_id,
    parse_epic_payload,
    parse_gamerpower_payload,
    parse_itad_rss,
)
from shared.safe_write import safe_write_text

OUTPUT_PATH = Path("curated/free_claims.auto.json")
USER_AGENT = "BAKLOG-fetch_claim_sources/1.0"
REQUEST_TIMEOUT = 30


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _fetch_json(url: str) -> dict | list:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, (dict, list)):
        raise ValueError(f"unexpected JSON type from {url}")
    return data


def _fetch_text(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.text


def fetch_epic_claims(*, now: datetime | None = None) -> list[dict]:
    payload = _fetch_json(EPIC_FREE_GAMES_URL)
    if not isinstance(payload, dict):
        raise ValueError("Epic feed must be a JSON object")
    return parse_epic_payload(payload, now=now)


def fetch_gamerpower_claims() -> list[dict]:
    payload = _fetch_json(GAMERPOWER_URL)
    if not isinstance(payload, list):
        raise ValueError("GamerPower feed must be a JSON array")
    return parse_gamerpower_payload(payload)


def fetch_itad_claims() -> list[dict]:
    xml_text = _fetch_text(ITAD_GIVEAWAYS_RSS)
    return parse_itad_rss(xml_text)


def collect_claims(
    sources: set[str],
    *,
    now: datetime | None = None,
    stats: RunStats | None = None,
) -> tuple[list[dict], dict[str, int]]:
    counts: dict[str, int] = {}
    collected: list[dict] = []

    if "epic" in sources:
        try:
            items = fetch_epic_claims(now=now)
            counts["epic"] = len(items)
            collected.extend(items)
        except (requests.RequestException, ValueError) as exc:
            if stats:
                stats.warn(f"Epic source skipped: {exc}")

    if "gamerpower" in sources:
        try:
            items = fetch_gamerpower_claims()
            counts["gamerpower"] = len(items)
            collected.extend(items)
        except (requests.RequestException, ValueError) as exc:
            if stats:
                stats.warn(f"GamerPower source skipped: {exc}")

    if "itad" in sources:
        try:
            items = fetch_itad_claims()
            counts["itad"] = len(items)
            collected.extend(items)
        except (requests.RequestException, ValueError) as exc:
            if stats:
                stats.warn(f"ITAD source skipped: {exc}")

    deduped = dedup_claim_items_by_id(collected)
    return deduped, counts


def _load_existing_items(output: Path) -> tuple[dict[str, dict], int]:
    """Return ({id: row}, total_row_count) from a prior auto feed, if present."""
    existing_by_id: dict[str, dict] = {}
    count = 0
    if output.is_file():
        try:
            old_doc = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return existing_by_id, 0
        for row in old_doc.get("items") or []:
            if not isinstance(row, dict):
                continue
            count += 1
            row_id = str(row.get("id") or "").strip()
            if row_id:
                existing_by_id[row_id] = row
    return existing_by_id, count


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--source",
        choices=("all", "epic", "gamerpower", "itad"),
        default="all",
        help="Which source(s) to fetch (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow writing an empty feed (e.g. genuinely no live giveaways).",
    )
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="Allow a feed sharply smaller than the prior run (partial source outage).",
    )
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("fetch_claim_sources.py")

    if args.source == "all":
        sources = {"epic", "gamerpower", "itad"}
    else:
        sources = {args.source}

    items, counts = collect_claims(sources, stats=stats)

    existing_by_id, prior_count = _load_existing_items(args.output)
    if existing_by_id:
        items = [
            carry_claim_enrichment(item, existing_by_id.get(str(item.get("id") or "").strip()))
            for item in items
        ]

    # Refuse to clobber a good feed with nothing (e.g. every source failed) —
    # mirrors the library fetcher exit-2 contract.
    code = refuse_empty_result(
        items,
        label="fetch_claim_sources",
        allow_empty=args.allow_empty,
        output_path=args.output,
    )
    if code is not None:
        return stats.finish("fetch_claim_sources", t0, exit_code=code)

    # Refuse a suspicious shrink vs the prior feed (partial source outage) so a
    # half-collected run can't silently halve the published claims (exit 3).
    if not args.allow_drift and prior_count > 0:
        floor = max(1, prior_count // 2)
        if len(items) < floor:
            stats.error(
                f"fetch_claim_sources collected {len(items)} item(s) but the prior feed "
                f"had {prior_count} (under the 50% floor) — likely a partial source outage. "
                "Re-run with --allow-drift if this drop is real."
            )
            return stats.finish("fetch_claim_sources", t0, exit_code=3)

    fetched_at = datetime.now(UTC).isoformat()
    has_gamerpower = any(item.get("source") == "gamerpower" for item in items)
    payload = {
        "fetched_at": fetched_at,
        "sources": counts,
        "attribution": [GAMERPOWER_ATTRIBUTION] if has_gamerpower else [],
        "items": items,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(
            f"dry-run: would write {len(items)} claim(s) to {args.output} "
            f"(sources: {counts or 'none'})",
            flush=True,
        )
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(args.output, text)
        print(
            f"Wrote {len(items)} claim(s) to {args.output} (sources: {counts or 'none'}).",
            flush=True,
        )

    stats.ok = len(items)
    return stats.finish("fetch_claim_sources", t0, exit_code=0, extra=f"{len(items)} claim(s)")


if __name__ == "__main__":
    raise SystemExit(main())
