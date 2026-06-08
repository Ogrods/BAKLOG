#!/usr/bin/env python3
"""Build the published free-claims feed from maintainer input + Steam enrichment."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from fetchers._progress import RunStats, started
from shared.free_claims_sources import GAMERPOWER_ATTRIBUTION, merge_manual_and_auto
from shared.profile_paths import free_claims_path
from shared.safe_write import safe_write_text

INPUT_PATH = Path("free-claims.input.json")
AUTO_PATH = Path("curated/free_claims.auto.json")
APPROVED_PATH = Path("curated/free_claims.approved.json")
OUTPUT_PATH = Path("landing/free-claims.json")
FALLBACK_PATH = Path("curated/free_claims.fallback.json")
STORE_DELAY_SEC = 1.5


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _slug_id(store: str, title: str, appid: int | None = None) -> str:
    if appid:
        return f"{store}-{appid}"
    base = re.sub(r"[^a-z0-9]+", "-", (title or "game").lower()).strip("-")
    return f"{store}-{base}"[:80] or f"{store}-claim"


def _throttle(last_call: list[float]) -> None:
    elapsed = time.time() - last_call[0]
    if elapsed < STORE_DELAY_SEC:
        time.sleep(STORE_DELAY_SEC - elapsed)
    last_call[0] = time.time()


def _steam_app_details(appid: int, last_call: list[float]) -> dict | None:
    _throttle(last_call)
    try:
        resp = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english"},
            timeout=30,
        )
        resp.raise_for_status()
        entry = resp.json().get(str(appid), {})
        if not entry.get("success"):
            return None
        return entry.get("data") or None
    except requests.RequestException:
        return None


def _steam_review_percent(appid: int, last_call: list[float]) -> int | None:
    _throttle(last_call)
    try:
        resp = requests.get(
            f"https://store.steampowered.com/appreviews/{appid}",
            params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
            timeout=30,
        )
        resp.raise_for_status()
        summary = resp.json().get("query_summary") or {}
        total = summary.get("total_reviews") or 0
        pos = summary.get("total_positive") or 0
        if total <= 0:
            return None
        return round(100 * pos / total)
    except requests.RequestException:
        return None


def _enrich_item(raw: dict, last_call: list[float]) -> dict:
    store = str(raw.get("store") or "").strip().lower()
    claim_url = str(raw.get("claim_url") or "").strip()
    title = (raw.get("title") or "").strip()
    appid = raw.get("steam_appid")
    if appid is not None:
        try:
            appid = int(appid)
        except (TypeError, ValueError):
            appid = None

    if appid and store in ("steam", ""):
        store = store or "steam"
        details = _steam_app_details(appid, last_call)
        if details:
            title = title or (details.get("name") or "").strip()
            header = details.get("header_image") or details.get("capsule_image")
            genres = [g.get("description") for g in (details.get("genres") or []) if g.get("description")]
            review = _steam_review_percent(appid, last_call)
        else:
            header = raw.get("header_image")
            genres = raw.get("genres") or []
            review = raw.get("review_percent")
    else:
        header = raw.get("header_image")
        genres = raw.get("genres") or []
        review = raw.get("review_percent")

    item_id = (raw.get("id") or "").strip() or _slug_id(store, title, appid)
    out = {
        "id": item_id,
        "store": store,
        "title": title or item_id,
        "claim_url": claim_url,
        "header_image": header,
        "genres": genres[:6] if isinstance(genres, list) else [],
        "blurb": raw.get("blurb"),
        "ends_at": raw.get("ends_at"),
    }
    if appid:
        out["steam_appid"] = appid
    if review is not None:
        out["review_percent"] = review
    source = raw.get("source")
    if source:
        out["source"] = source
    return out


def _load_auto_items(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = doc.get("items") or []
    return items if isinstance(items, list) else []


def _load_approved_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = doc.get("ids") or []
    if not isinstance(ids, list):
        return set()
    return {str(item_id).strip() for item_id in ids if str(item_id).strip()}


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Skip writing the active profile's free_claims.json (publish-only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stats = RunStats()
    t0 = started("build_free_claims.py")

    if not args.input.is_file():
        stats.error(f"missing input file: {args.input}")
        return stats.finish("build_free_claims", t0, exit_code=1)

    try:
        doc = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        stats.error(f"could not read input: {exc}")
        return stats.finish("build_free_claims", t0, exit_code=1)

    manual_items = doc.get("items") or []
    if not isinstance(manual_items, list):
        stats.error("input.items must be a list")
        return stats.finish("build_free_claims", t0, exit_code=1)

    auto_items_all = _load_auto_items(AUTO_PATH)
    approved_ids = _load_approved_ids(APPROVED_PATH)
    auto_items = [
        item
        for item in auto_items_all
        if str(item.get("id") or "").strip() in approved_ids
    ]
    if auto_items_all:
        stats.warn(
            f"auto feed: {len(auto_items)} approved of {len(auto_items_all)} available"
        )
    raw_items = merge_manual_and_auto(manual_items, auto_items)
    if auto_items:
        stats.warn(f"merged {len(auto_items)} auto item(s); {len(raw_items)} total before enrich")

    last_call = [0.0]
    items: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            stats.warn("skipped non-object item")
            continue
        if not raw.get("claim_url") or not raw.get("store"):
            stats.warn(f"skipped item missing store/claim_url: {raw!r}")
            continue
        items.append(_enrich_item(raw, last_call))

    generated_at = datetime.now(UTC).isoformat()
    has_gamerpower = any(item.get("source") == "gamerpower" for item in items)
    payload = {
        "generated_at": generated_at,
        "items": items,
    }
    if has_gamerpower:
        payload["attribution"] = [GAMERPOWER_ATTRIBUTION]
    profile_payload = {
        "fetched_at": generated_at,
        "source_url": "build_free_claims.py",
        "generated_at": generated_at,
        "items": items,
    }
    if has_gamerpower:
        profile_payload["attribution"] = [GAMERPOWER_ATTRIBUTION]
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    profile_text = json.dumps(profile_payload, indent=2, ensure_ascii=False)

    if args.dry_run:
        targets = [args.output, FALLBACK_PATH]
        if not args.no_profile:
            targets.append(free_claims_path())
        print(
            f"dry-run: would write {len(items)} item(s) to {', '.join(str(t) for t in targets)}",
            flush=True,
        )
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_PATH.write_text(text, encoding="utf-8")
        written = [args.output, FALLBACK_PATH]
        if not args.no_profile:
            profile_out = free_claims_path()
            safe_write_text(profile_out, profile_text)
            written.append(profile_out)
        print(
            f"Wrote {len(items)} item(s) to {', '.join(str(p) for p in written)}.",
            flush=True,
        )

    stats.ok = len(items)
    return stats.finish("build_free_claims", t0, exit_code=0, extra=f"{len(items)} item(s)")


if __name__ == "__main__":
    raise SystemExit(main())
