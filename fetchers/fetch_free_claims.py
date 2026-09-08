#!/usr/bin/env python3
"""Download the maintainer-curated free-claimable games feed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from fetchers._base import (
    add_allow_empty_arg,
    configure_stdout,
    refuse_drift_result,
    refuse_empty_result,
)
from fetchers._progress import RunStats, started
from shared.free_claims_sources import has_valid_claim_links
from shared.profile_paths import free_claims_path
from shared.safe_write import safe_write_text

DEFAULT_URL = "https://baklog.app/free-claims.json"
USER_AGENT = "BAKLOG-fetch_free_claims/1.0"


def _parse_feed_timestamp(value: object) -> datetime | None:
    """Parse a feed ``generated_at`` / ``fetched_at`` string to UTC, or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _local_feed_timestamp(doc: dict) -> datetime | None:
    """Newest of local ``generated_at`` / ``fetched_at`` (admin publish or last fetch)."""
    stamps = [
        ts
        for ts in (
            _parse_feed_timestamp(doc.get("generated_at")),
            _parse_feed_timestamp(doc.get("fetched_at")),
        )
        if ts is not None
    ]
    return max(stamps) if stamps else None


def refuse_older_hosted_result(
    hosted: dict,
    *,
    output_path: Path | None,
    allow_drift: bool,
) -> int | None:
    """Return exit code 3 when hosted ``generated_at`` is older than the local feed.

    Prevents a lagging baklog.app deploy from overwriting a fresher admin-publish
    (or local build) after count-based drift alone would allow the write.
    ``--allow-drift`` opts out. Missing timestamps skip the check.
    """
    if allow_drift or output_path is None or not output_path.is_file():
        return None
    hosted_ts = _parse_feed_timestamp(hosted.get("generated_at"))
    if hosted_ts is None:
        return None
    try:
        local_doc = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(local_doc, dict):
        return None
    local_ts = _local_feed_timestamp(local_doc)
    if local_ts is None or hosted_ts >= local_ts:
        return None
    print(
        f"ERROR: hosted free-claims feed generated_at ({hosted_ts.isoformat()}) "
        f"is older than the local feed ({local_ts.isoformat()} at {output_path}).\n"
        "Refusing to overwrite a newer local publish. Re-run with --allow-drift "
        "to force, or wait until baklog.app catches up.",
        file=sys.stderr,
        flush=True,
    )
    return 3


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
    configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("BAKLOG_CLAIMS_URL", DEFAULT_URL),
        help="Hosted feed URL (default: BAKLOG_CLAIMS_URL or baklog.app)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write")
    add_allow_empty_arg(parser)
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("fetch_free_claims.py")

    try:
        data = _fetch_url(args.url)
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        stats.error(f"could not load feed: {exc}")
        return stats.finish("fetch_free_claims", t0, exit_code=1)

    raw_items = data.get("items") or []
    valid_items: list[dict] = []
    invalid = 0
    dropped_ids: list[str] = []
    for item in raw_items:
        if not isinstance(item, dict):
            invalid += 1
            dropped_ids.append("<non-object>")
            continue
        if not item.get("id") or not item.get("store") or not has_valid_claim_links(item):
            invalid += 1
            dropped_ids.append(str(item.get("id") or "<missing-id>"))
            continue
        valid_items.append(item)
    valid = len(valid_items)
    if invalid:
        sample = ", ".join(dropped_ids[:5])
        more = f" (+{invalid - 5} more)" if invalid > 5 else ""
        stats.warn(
            f"dropped {invalid} malformed claim row(s) "
            f"(need id, store, and valid claim link(s)): {sample}{more}"
        )

    out = free_claims_path()
    empty_exit = refuse_empty_result(
        valid_items,
        label="hosted free-claims feed",
        allow_empty=args.allow_empty,
        output_path=out,
    )
    if empty_exit is not None:
        return stats.finish("fetch_free_claims", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        valid_items,
        label="hosted free-claims feed",
        allow_drift=args.allow_drift,
        output_path=out,
    )
    if drift_exit is not None:
        return stats.finish("fetch_free_claims", t0, exit_code=drift_exit)
    older_exit = refuse_older_hosted_result(
        data,
        output_path=out,
        allow_drift=args.allow_drift,
    )
    if older_exit is not None:
        return stats.finish("fetch_free_claims", t0, exit_code=older_exit)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "source_url": args.url,
        "generated_at": data.get("generated_at"),
        "items": valid_items,
    }
    attribution = data.get("attribution")
    if isinstance(attribution, list) and attribution:
        payload["attribution"] = attribution

    if args.dry_run:
        print(f"dry-run: would write {valid} claim(s) to {out}", flush=True)
    else:
        safe_write_text(out, json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"Wrote {valid} claim(s) to {out}.", flush=True)

    stats.ok = valid
    return stats.finish("fetch_free_claims", t0, exit_code=0, extra=f"{valid} claim(s)")


if __name__ == "__main__":
    raise SystemExit(main())
