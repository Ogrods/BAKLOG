#!/usr/bin/env python3
"""Download the maintainer-curated free-claimable games feed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from fetchers._progress import RunStats, started
from shared.profile_paths import free_claims_path
from shared.safe_write import safe_write_text

DEFAULT_URL = "https://baklog.app/free-claims.json"
USER_AGENT = "BAKLOG-fetch_free_claims/1.0"


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _fetch_url(url: str, *, timeout: int = 30) -> dict:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("feed must be a JSON object")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("feed.items must be a list")
    return data


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("BAKLOG_CLAIMS_URL", DEFAULT_URL),
        help="Hosted feed URL (default: BAKLOG_CLAIMS_URL or baklog.app)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write")
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("fetch_free_claims.py")

    try:
        data = _fetch_url(args.url)
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        stats.error(f"could not load feed: {exc}")
        return stats.finish("fetch_free_claims", t0, exit_code=1)

    items = data.get("items") or []
    valid = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("id") or not item.get("claim_url") or not item.get("store"):
            continue
        valid += 1

    if valid == 0 and items:
        stats.error("feed has items but none passed validation (need id, store, claim_url)")
        return stats.finish("fetch_free_claims", t0, exit_code=2)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "source_url": args.url,
        "generated_at": data.get("generated_at"),
        "items": items,
    }

    out = free_claims_path()
    if args.dry_run:
        print(f"dry-run: would write {valid} claim(s) to {out}", flush=True)
    else:
        safe_write_text(out, json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"Wrote {valid} claim(s) to {out}.", flush=True)

    stats.ok = valid
    return stats.finish("fetch_free_claims", t0, exit_code=0, extra=f"{valid} claim(s)")


if __name__ == "__main__":
    raise SystemExit(main())
