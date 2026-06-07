#!/usr/bin/env python3
"""Fetch auto-discovered free claimable games from Epic, GamerPower, and ITAD RSS."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

from fetchers._progress import RunStats, started
from shared.free_claims_sources import (
    EPIC_FREE_GAMES_URL,
    GAMERPOWER_ATTRIBUTION,
    GAMERPOWER_URL,
    ITAD_GIVEAWAYS_RSS,
    dedup_claim_items,
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

    deduped = dedup_claim_items(collected)
    return deduped, counts


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
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("fetch_claim_sources.py")

    if args.source == "all":
        sources = {"epic", "gamerpower", "itad"}
    else:
        sources = {args.source}

    items, counts = collect_claims(sources, stats=stats)
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
