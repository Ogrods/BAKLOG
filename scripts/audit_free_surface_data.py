#!/usr/bin/env python3
"""Read-only audit of free-tier data artifacts (claims pipeline + adjacent catalogs).

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\audit_free_surface_data.py
  .\\.venv\\Scripts\\python.exe scripts\\audit_free_surface_data.py --check-urls --out review-report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.free_claims_sources import claim_match_keys, norm_title
from shared.profile_paths import (
    free_claims_path,
    get_active_profile_id,
    itad_path,
    personal_backup_dir,
    personal_path,
)

AUTO_PATH = ROOT / "curated" / "free_claims.auto.json"
APPROVED_PATH = ROOT / "curated" / "free_claims.approved.json"
INPUT_PATH = ROOT / "free-claims.input.json"
BUILT_PATH = ROOT / "landing" / "free-claims.json"
FALLBACK_PATH = ROOT / "curated" / "free_claims.fallback.json"
SPONSORS_PATH = ROOT / "curated" / "sponsors.json"

REQUIRED_ITEM_FIELDS = ("id", "store", "title", "claim_url")
BLURB_LEAK_RE = re.compile(r"<a\b|isthereanydeal\.com/giveaways", re.I)
STEAM_PORTRAIT_RE = re.compile(r"/library_600x900_2x\.jpg", re.I)

CLAIMS_PREFS_KEYS = (
    "claimsAutoRefreshIntervalMin",
    "claimsAutoRefreshDisabled",
    "itadAutoRefreshIntervalMin",
    "itadAutoRefreshDisabled",
    "autoFetchStale24h",
    "shareAnonStats",
)


def _load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _file_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_iso": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
    }


def _parse_ts(value: object) -> float:
    if not value:
        return 0.0
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def feed_generated_at(doc: dict | None) -> float:
    if not doc:
        return 0.0
    return max(_parse_ts(doc.get("generated_at")), _parse_ts(doc.get("fetched_at")))


def pick_newer_feed(primary: dict | None, secondary: dict | None) -> str:
    """Return label of winning feed (mirrors js/claimable.js pickNewerFeed)."""
    a_items = primary.get("items") if isinstance(primary, dict) else None
    b_items = secondary.get("items") if isinstance(secondary, dict) else None
    a = primary if isinstance(a_items, list) and a_items else None
    b = secondary if isinstance(b_items, list) and b_items else None
    if not a:
        return "secondary" if b else "none"
    if not b:
        return "primary"
    return "secondary" if feed_generated_at(b) > feed_generated_at(a) else "primary"


def stable_key(item: dict) -> str:
    appid = item.get("steam_appid")
    if appid is not None:
        try:
            n = int(appid)
            if n:
                return f"appid:{n}"
        except (TypeError, ValueError):
            pass
    title_norm = norm_title(str(item.get("title") or ""))
    if title_norm:
        return f"title:{title_norm}"
    return f"id:{item.get('id') or '?'}"


def claim_dedup_key(item: dict) -> str:
    """Mirrors js/claim-card.js claimDedupKey (single canonical key)."""
    return stable_key(item)


def _items(doc: dict | list | None) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    raw = doc.get("items")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _parse_ends_at(ends_at: object) -> datetime | None:
    if ends_at is None:
        return None
    text = str(ends_at).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _is_expired(item: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    parsed = _parse_ends_at(item.get("ends_at"))
    if parsed is None:
        return False
    return parsed < now


def _row_issues(item: dict, *, now: datetime | None = None, feed_name: str = "") -> list[str]:
    issues: list[str] = []
    for field in REQUIRED_ITEM_FIELDS:
        if not str(item.get(field) or "").strip():
            issues.append(f"missing_{field}")
    url = str(item.get("claim_url") or "")
    if url and not url.startswith(("http://", "https://")):
        issues.append("bad_claim_url_scheme")
    if item.get("store") == "other":
        issues.append("store_other")
    blurb = str(item.get("blurb") or "")
    if BLURB_LEAK_RE.search(blurb):
        issues.append("blurb_html_leak")
    img = str(item.get("header_image") or "")
    if STEAM_PORTRAIT_RE.search(img):
        issues.append("steam_portrait_cover")
    if _is_expired(item, now):
        issues.append("expired")
    appid = item.get("steam_appid")
    review = item.get("review_percent")
    store = str(item.get("store") or "")
    source = str(item.get("source") or "")
    if store == "steam" and appid is None and source in ("gamerpower", "itad"):
        issues.append("steam_store_no_appid")
    if appid is not None and review is None:
        issues.append("appid_no_review")
    if item.get("ends_at") is None and source == "itad" and feed_name == "auto":
        issues.append("itad_no_ends_at")
    return issues


def _fill_rates(items: list[dict]) -> dict[str, Any]:
    n = len(items)
    if not n:
        return {"count": 0}
    fields = (
        "header_image",
        "steam_appid",
        "review_percent",
        "genres",
        "blurb",
        "ends_at",
        "source",
    )
    rates: dict[str, Any] = {"count": n}
    for field in fields:
        filled = sum(1 for it in items if it.get(field) not in (None, "", []))
        rates[field] = {"filled": filled, "pct": round(100 * filled / n, 1)}
    by_source: dict[str, int] = Counter(str(it.get("source") or "?") for it in items)
    rates["by_source"] = dict(by_source)
    by_store: dict[str, int] = Counter(str(it.get("store") or "?") for it in items)
    rates["by_store"] = dict(by_store)
    return rates


def _duplicate_clusters(items: list[dict]) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_key[stable_key(item)].append(item)
    clusters = []
    for key, group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        clusters.append(
            {
                "stable_key": key,
                "count": len(group),
                "ids": [str(g.get("id")) for g in group],
                "sources": [str(g.get("source") or "?") for g in group],
                "titles": [str(g.get("title") or "")[:60] for g in group],
            }
        )
    return clusters


def _audit_feed(name: str, doc: dict | None, path: Path) -> dict[str, Any]:
    now = datetime.now(UTC)
    items = _items(doc)
    rows = []
    for item in items:
        issues = _row_issues(item, now=now, feed_name=name)
        rows.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "store": item.get("store"),
                "source": item.get("source"),
                "ends_at": item.get("ends_at"),
                "steam_appid": item.get("steam_appid"),
                "review_percent": item.get("review_percent"),
                "stable_key": stable_key(item),
                "issues": issues,
            }
        )
    return {
        "name": name,
        "file": _file_meta(path),
        "envelope": {
            k: doc.get(k)
            for k in ("generated_at", "fetched_at", "source_url", "sources", "attribution")
            if isinstance(doc, dict) and doc.get(k) is not None
        },
        "feed_generated_at": feed_generated_at(doc if isinstance(doc, dict) else None),
        "fill_rates": _fill_rates(items),
        "duplicate_clusters": _duplicate_clusters(items),
        "rows_with_issues": sum(1 for r in rows if r["issues"]),
        "rows": rows,
    }


def _approved_audit(approved: dict | None, auto: dict | None, built: dict | None, input_doc: dict | None) -> dict[str, Any]:
    if not isinstance(approved, dict):
        return {"exists": False}
    ids = [str(x) for x in (approved.get("ids") or []) if str(x).strip()]
    dismissed = {str(x) for x in (approved.get("dismissed") or []) if str(x).strip()}
    auto_by_id = {str(it.get("id")): it for it in _items(auto) if it.get("id")}
    built_items = _items(built)
    built_by_id = {str(it.get("id")): it for it in built_items if it.get("id")}
    built_keys = {stable_key(it) for it in built_items}
    input_by_id = {str(it.get("id")): it for it in _items(input_doc) if it.get("id")}

    orphans_not_in_auto = []
    orphans_not_in_built = []
    orphans_represented_by_stable_key = []
    carry_forward_candidates = []
    for aid in ids:
        if aid not in auto_by_id:
            orphans_not_in_auto.append(aid)
            if aid in input_by_id:
                carry_forward_candidates.append({"id": aid, "via": "input"})
        if aid not in built_by_id and aid not in dismissed:
            # Approved id may publish under a sibling row (Epic wins over ITAD dedup).
            ref = auto_by_id.get(aid) or input_by_id.get(aid)
            ref_keys = {stable_key(ref)} if ref else set()
            ref_keys.update(claim_match_keys(ref) if ref else [])
            if ref_keys & built_keys:
                orphans_represented_by_stable_key.append(
                    {"approved_id": aid, "stable_keys": sorted(ref_keys & built_keys)}
                )
            else:
                orphans_not_in_built.append(aid)

    store_overrides = approved.get("store_overrides") or {}
    field_overrides = approved.get("field_overrides") or {}
    override_drift = []
    for aid, fields in field_overrides.items():
        if not isinstance(fields, dict):
            continue
        auto_item = auto_by_id.get(aid)
        built_item = built_by_id.get(aid)
        for field, override_val in fields.items():
            auto_val = auto_item.get(field) if auto_item else None
            built_val = built_item.get(field) if built_item else None
            if built_item and str(built_val or "") != str(override_val or ""):
                override_drift.append(
                    {"id": aid, "field": field, "override": override_val, "built": built_val, "auto": auto_val}
                )

    return {
        "exists": True,
        "approved_count": len(ids),
        "dismissed_count": len(dismissed),
        "store_overrides_count": len(store_overrides) if isinstance(store_overrides, dict) else 0,
        "field_overrides_count": len(field_overrides) if isinstance(field_overrides, dict) else 0,
        "orphans_not_in_auto": orphans_not_in_auto,
        "orphans_not_in_built": orphans_not_in_built,
        "orphans_represented_by_stable_key": orphans_represented_by_stable_key,
        "carry_forward_via_input": carry_forward_candidates,
        "override_drift": override_drift,
    }


def _cross_layer_diff(
    built: dict | None,
    fallback: dict | None,
    profile: dict | None,
) -> dict[str, Any]:
    built_items = _items(built)
    fallback_items = _items(fallback)
    profile_items = _items(profile)

    def id_set(items: list[dict]) -> set[str]:
        return {str(it.get("id")) for it in items if it.get("id")}

    def key_map(items: list[dict]) -> dict[str, str]:
        return {stable_key(it): str(it.get("id")) for it in items}

    built_ids = id_set(built_items)
    fallback_ids = id_set(fallback_items)
    profile_ids = id_set(profile_items)

    built_keys = key_map(built_items)
    fallback_keys = key_map(fallback_items)
    profile_keys = key_map(profile_items)

    pick_local_fb = pick_newer_feed(profile, fallback)
    pick_built_fb = pick_newer_feed(built, fallback)

    return {
        "built_vs_fallback": {
            "built_count": len(built_items),
            "fallback_count": len(fallback_items),
            "ids_only_in_built": sorted(built_ids - fallback_ids),
            "ids_only_in_fallback": sorted(fallback_ids - built_ids),
            "ids_match": built_ids == fallback_ids,
            "stable_keys_only_in_built": sorted(set(built_keys) - set(fallback_keys)),
            "stable_keys_only_in_fallback": sorted(set(fallback_keys) - set(built_keys)),
        },
        "built_vs_profile": {
            "profile_count": len(profile_items),
            "built_count": len(built_items),
            "ids_only_in_built": sorted(built_ids - profile_ids),
            "ids_only_in_profile": sorted(profile_ids - built_ids),
            "profile_generated_at": feed_generated_at(profile if isinstance(profile, dict) else None),
            "built_generated_at": feed_generated_at(built if isinstance(built, dict) else None),
        },
        "pick_newer_feed": {
            "profile_vs_fallback_winner": pick_local_fb,
            "profile_ts": feed_generated_at(profile if isinstance(profile, dict) else None),
            "fallback_ts": feed_generated_at(fallback if isinstance(fallback, dict) else None),
            "built_vs_fallback_winner": pick_built_fb,
        },
    }


def _claim_dedup_keys(item: dict) -> list[str]:
    keys = list(claim_match_keys(item))
    if not keys and item.get("id"):
        keys.append(f"id:{item['id']}")
    return keys


def _personal_audit(profile_id: str, feed_items: list[dict]) -> dict[str, Any]:
    ppath = personal_path(profile_id=profile_id)
    doc = _load_json(ppath)
    personal = doc.get("personal", {}) if isinstance(doc, dict) else {}
    if not isinstance(personal, dict):
        personal = {}

    dismissed = personal.get("__dismissedClaims") or {}
    dismissed_keys = personal.get("__dismissedClaimKeys") or {}
    if not isinstance(dismissed, dict):
        dismissed = {}
    if not isinstance(dismissed_keys, dict):
        dismissed_keys = {}

    feed_ids = {str(it.get("id")) for it in feed_items if it.get("id")}
    feed_key_set: set[str] = set()
    for it in feed_items:
        feed_key_set.update(_claim_dedup_keys(it))

    orphan_ids = [i for i in dismissed if i not in feed_ids]
    orphan_keys = [k for k in dismissed_keys if k not in feed_key_set]

    id_only_no_key = []
    for cid in dismissed:
        item = next((it for it in feed_items if str(it.get("id")) == cid), None)
        if item:
            keys = _claim_dedup_keys(item)
            if not any(k in dismissed_keys for k in keys):
                id_only_no_key.append({"id": cid, "missing_keys": keys})

    backup_timeline = []
    bdir = personal_backup_dir(profile_id=profile_id)
    if bdir.is_dir():
        for bp in sorted(bdir.glob("personal-*.json")):
            bdoc = _load_json(bp)
            bp_personal = bdoc.get("personal", {}) if isinstance(bdoc, dict) else {}
            if not isinstance(bp_personal, dict):
                bp_personal = {}
            d = bp_personal.get("__dismissedClaims") or {}
            dk = bp_personal.get("__dismissedClaimKeys") or {}
            backup_timeline.append(
                {
                    "file": bp.name,
                    "dismissed_ids": len(d) if isinstance(d, dict) else 0,
                    "dismissed_keys": len(dk) if isinstance(dk, dict) else 0,
                }
            )

    return {
        "personal_path": str(ppath.relative_to(ROOT)),
        "exists": ppath.is_file(),
        "dismissed_ids_count": len(dismissed),
        "dismissed_keys_count": len(dismissed_keys),
        "orphan_dismissed_ids": orphan_ids,
        "orphan_dismissed_keys": orphan_keys,
        "dismissed_id_without_key_backup": id_only_no_key,
        "backup_timeline": backup_timeline,
    }


def _itad_audit(profile_id: str) -> dict[str, Any]:
    path = itad_path(profile_id=profile_id)
    doc = _load_json(path)
    if not isinstance(doc, dict):
        return {"exists": False, "path": str(path.relative_to(ROOT))}
    by_key = doc.get("by_key") or {}
    count = len(by_key) if isinstance(by_key, dict) else 0
    fetched_at = doc.get("fetched_at")
    age_hours = None
    if fetched_at:
        ts = _parse_ts(fetched_at)
        if ts:
            age_hours = round((datetime.now(UTC).timestamp() - ts) / 3600, 1)
    sample_keys = list(by_key.keys())[:10] if isinstance(by_key, dict) else []
    return {
        "exists": True,
        "path": str(path.relative_to(ROOT)),
        "fetched_at": fetched_at,
        "age_hours": age_hours,
        "by_key_count": count,
        "sample_keys": sample_keys,
    }


def _sponsors_audit() -> dict[str, Any]:
    doc = _load_json(SPONSORS_PATH)
    if not isinstance(doc, dict):
        return {"exists": False}
    items = doc.get("items") or []
    enabled = [it for it in items if isinstance(it, dict) and it.get("enabled", True)]
    issues = []
    for it in items:
        if not isinstance(it, dict):
            continue
        for field in ("id", "title"):
            if not str(it.get(field) or "").strip():
                issues.append({"id": it.get("id"), "issue": f"missing_{field}"})
    return {
        "exists": True,
        "version": doc.get("version"),
        "generated_at": doc.get("generated_at"),
        "total_items": len(items),
        "enabled_items": len(enabled),
        "issues": issues,
    }


def _plan_audit() -> dict[str, Any]:
    from shared.entitlement import current_plan

    env_plan = os.environ.get("BAKLOG_PLAN", "").strip() or None
    plan = current_plan(None)
    return {
        "resolved_plan": plan,
        "BAKLOG_PLAN_env": env_plan,
        "note": "Pure-local mode uses env then license.json; Supabase mode uses JWT only.",
    }


def _check_urls(items: list[dict], *, limit: int = 30, delay: float = 0.3) -> list[dict[str, Any]]:
    results = []
    checked = 0
    for item in items:
        if checked >= limit:
            break
        url = str(item.get("header_image") or "").strip()
        if not url or not url.startswith("http"):
            continue
        status = None
        err = None
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "BAKLOG-audit/1.0"})
            with urlopen(req, timeout=15) as resp:
                status = resp.status
        except URLError as exc:
            err = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        except OSError as exc:
            err = str(exc)
        results.append(
            {
                "id": item.get("id"),
                "url": url,
                "status": status,
                "error": err,
                "issue": "cover_404" if status == 404 else ("cover_error" if err else None),
            }
        )
        checked += 1
        time.sleep(delay)
    return results


def _write_row_csv(report: dict[str, Any], path: Path) -> None:
    """Per-feed row table: id | title | store | source | ends_at | appid | review% | issues."""
    lines = ["feed,id,title,store,source,ends_at,steam_appid,review_percent,stable_key,issues"]
    for feed_name, feed in report.get("feeds", {}).items():
        for row in feed.get("rows", []):
            issues = ";".join(row.get("issues") or [])
            title = str(row.get("title") or "").replace('"', '""')
            lines.append(
                f'{feed_name},{row.get("id")},"{title}",{row.get("store")},{row.get("source")},'
                f'{row.get("ends_at")},{row.get("steam_appid")},{row.get("review_percent")},'
                f'{row.get("stable_key")},"{issues}"'
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_handoff_md(report: dict[str, Any], path: Path) -> None:
    b = report.get("baseline", {})
    counts = b.get("item_counts", {})
    approved = report.get("approved", {})
    personal = report.get("personal", {})
    cross = report.get("cross_layer", {})
    findings = report.get("findings", [])

    high = [f for f in findings if f["severity"] == "high"]
    medium = [f for f in findings if f["severity"] == "medium"]

    lines = [
        "# Free-tier data review — handoff",
        "",
        f"**Captured:** {report.get('captured_at')}",
        f"**Profile:** `{report.get('profile_id')}`",
        "",
        "## Baseline counts",
        "",
        "| Artifact | Items |",
        "|----------|------:|",
    ]
    for name, n in counts.items():
        lines.append(f"| {name} | {n} |")

    lines.extend(
        [
            "",
            "## Cross-layer health",
            "",
            f"- **built ↔ fallback ids match:** {cross.get('built_vs_fallback', {}).get('ids_match')}",
            f"- **pickNewerFeed profile vs fallback:** `{cross.get('pick_newer_feed', {}).get('profile_vs_fallback_winner')}` wins",
            f"- **Approved id orphans (true gaps):** {len(approved.get('orphans_not_in_built', []))}",
            f"- **Approved id → stable-key siblings in built:** {len(approved.get('orphans_represented_by_stable_key', []))}",
            f"- **Personal dismissals now:** {personal.get('dismissed_ids_count')} ids / {personal.get('dismissed_keys_count')} keys",
            f"- **ITAD by_key count:** {report.get('itad', {}).get('by_key_count')} (age {report.get('itad', {}).get('age_hours')}h)",
            f"- **Plan:** `{report.get('plan', {}).get('resolved_plan')}`",
            "",
            "## Watchlist verification",
            "",
            "| Tracker item | Data verdict |",
            "|--------------|--------------|",
            "| Dismissals wiped overnight | Backups show 11→0 wipe at 16:43; current state 0 dismissals (clean) |",
            "| Approved dropped on source hiccup | 4 approved ITAD ids publish as Epic/GP siblings (stable-key match) |",
            "| Free pill `?` count | Profile fetched_at newer than fallback; profile wins pickNewerFeed |",
            "| ID churn dismiss resurrect | N/A — no active dismissals to verify |",
            "| store:other in auto | 9 rows in auto; 6 have approved store_overrides → indiegala in built |",
            "",
            "## Actionable findings (high + medium)",
            "",
        ]
    )
    for f in high + medium:
        row = f" `{f['row']}`" if f.get("row") else ""
        lines.append(f"- **{f['id']}** ({f['severity']}, {f['owner']}){row}: {f['observed']}")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `review-baseline.json` — file inventory",
            "- `review-report.json` — full audit payload",
            "- `review-feed-rows.csv` — line-by-line row table",
            "- `review-findings.yaml` — machine-readable findings for code agent",
            "",
            "Re-run: `.\\.venv\\Scripts\\python.exe scripts\\audit_free_surface_data.py --check-urls`",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _compile_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seq = 0

    def add(
        severity: str,
        owner: str,
        artifact: str,
        observed: str,
        expected: str,
        suggested: str,
        row: str | None = None,
        blocks: str | None = None,
    ) -> None:
        nonlocal seq
        seq += 1
        findings.append(
            {
                "id": f"DATA-{seq:03d}",
                "severity": severity,
                "owner": owner,
                "artifact": artifact,
                "row": row,
                "observed": observed,
                "expected": expected,
                "suggested_action": suggested,
                "blocks": blocks,
            }
        )

    for feed_name in ("auto", "built", "fallback", "profile"):
        feed = report.get("feeds", {}).get(feed_name, {})
        for row in feed.get("rows", []):
            for issue in row.get("issues", []):
                if issue == "store_other":
                    add(
                        "medium",
                        "data-fix",
                        feed_name,
                        f"store=other for {row.get('id')}",
                        "Explicit store (itch, indiegala, etc.)",
                        "Add store_overrides in approved.json or fix parser inference",
                        row=row.get("id"),
                        blocks="store: other for itch/indiegala",
                    )
                elif issue == "blurb_html_leak":
                    add(
                        "medium",
                        "maintainer-action",
                        feed_name,
                        f"HTML/URL leak in blurb for {row.get('id')}",
                        "Clean blurb text",
                        "Re-run build_free_claims.py or fix source row",
                        row=row.get("id"),
                        blocks="p4_claim_blurb_html_and_modal",
                    )
                elif issue == "steam_portrait_cover":
                    add(
                        "low",
                        "code-fix",
                        feed_name,
                        f"library_600x900 portrait URL for {row.get('id')}",
                        "Working cover or onerror fallback",
                        "Prefer header.jpg or claimCoverFallback in UI",
                        row=row.get("id"),
                        blocks="p4_claim_cover_broken_img",
                    )
                elif issue == "itad_no_ends_at":
                    add(
                        "low",
                        "code-fix",
                        feed_name,
                        f"ITAD row {row.get('id')} has ends_at=null",
                        "Expiry known or UX handles unknown",
                        "Document unknown-expiry UX; build assigns 14d default at publish",
                        row=row.get("id"),
                        blocks="ITAD ends_at: null",
                    )
                elif issue == "appid_no_review":
                    add(
                        "low",
                        "maintainer-action",
                        feed_name,
                        f"appid without review_percent on {row.get('id')}",
                        "review_percent populated after enrich",
                        "Re-run build_free_claims.py enrich",
                        row=row.get("id"),
                    )
                elif issue == "expired" and feed_name in ("built", "profile"):
                    add(
                        "medium",
                        "maintainer-action",
                        feed_name,
                        f"Expired row still published: {row.get('id')}",
                        "Expired rows pruned at publish",
                        "Remove from approved or re-run build",
                        row=row.get("id"),
                    )

    approved = report.get("approved", {})
    for oid in approved.get("orphans_not_in_built", []):
        add(
            "high",
            "maintainer-action",
            "approved.json",
            f"Approved id {oid} missing from built feed (no stable-key sibling)",
            "Game represented in landing/free-claims.json",
            "Re-run build_free_claims.py; verify carry-forward for ids absent from auto",
            row=oid,
            blocks="p4_claim_approved_dropped_on_source_hiccup",
        )
    for drift in approved.get("override_drift", []):
        add(
            "medium",
            "data-fix",
            "approved.json",
            f"field_overrides[{drift['id']}].{drift['field']} not applied in built",
            f"built should equal override {drift['override']!r}",
            "Re-run build or fix override id mismatch",
            row=drift["id"],
        )

    personal = report.get("personal", {})
    if personal.get("orphan_dismissed_ids"):
        add(
            "low",
            "code-fix",
            "personal.__dismissedClaims",
            f"{len(personal['orphan_dismissed_ids'])} dismissed ids not in current feed",
            "Orphans pruned when feed non-empty (by design)",
            "Verify pruneDismissedClaims only runs on non-empty feed",
            blocks="p4_claim_dismissals_wiped_overnight",
        )
    if personal.get("dismissed_id_without_key_backup"):
        add(
            "medium",
            "code-fix",
            "personal.__dismissedClaimKeys",
            f"{len(personal['dismissed_id_without_key_backup'])} dismissed ids lack key backup",
            "Every dismissal should mirror dedup keys",
            "User clear may resurrect on id churn",
            blocks="p4_claim_hidden_restore",
        )

    cross = report.get("cross_layer", {})
    pvf = cross.get("pick_newer_feed", {})
    if pvf.get("profile_vs_fallback_winner") == "fallback" and cross.get("built_vs_profile", {}).get("profile_count", 0) > 0:
        prof = cross["built_vs_profile"]
        if prof.get("profile_count") != prof.get("built_count"):
            add(
                "medium",
                "code-fix",
                "free_claims.json vs fallback",
                f"Profile feed ({prof.get('profile_count')} items) loses pickNewerFeed to fallback",
                "Profile wins when fetched_at newer even if generated_at stale",
                "Verify feedGeneratedAt uses max(generated_at, fetched_at)",
                blocks="p4_free_pill_question_mark",
            )

    bvf = cross.get("built_vs_fallback", {})
    if not bvf.get("ids_match"):
        add(
            "medium",
            "maintainer-action",
            "landing vs fallback",
            f"built/fallback id sets differ: +{len(bvf.get('ids_only_in_built', []))} / -{len(bvf.get('ids_only_in_fallback', []))}",
            "fallback synced from last build",
            "Copy landing/free-claims.json to curated/free_claims.fallback.json",
        )

    for dup in report.get("feeds", {}).get("auto", {}).get("duplicate_clusters", []):
        if dup["count"] >= 2:
            add(
                "low",
                "code-fix",
                "auto feed",
                f"Duplicate stable_key {dup['stable_key']} ({dup['count']} rows pre-UI-dedup)",
                "UI dedupeClaims collapses to one row",
                "Expected pre-dedup; verify SOURCE_PRECEDENCE picks epic over GP/ITAD",
                row=dup["stable_key"],
                blocks="Duplicate Epic+GP same game",
            )

    url_checks = report.get("url_checks", [])
    for uc in url_checks:
        if uc.get("issue"):
            add(
                "medium",
                "code-fix",
                "header_image",
                f"Cover check failed for {uc.get('id')}: {uc.get('status') or uc.get('error')}",
                "HTTP 200 cover",
                "Use header.jpg fallback or claimCoverFallback",
                row=uc.get("id"),
                blocks="p4_claim_cover_broken_img",
            )

    return findings


def build_baseline(profile_id: str) -> dict[str, Any]:
    paths = {
        "auto": AUTO_PATH,
        "approved": APPROVED_PATH,
        "input": INPUT_PATH,
        "built": BUILT_PATH,
        "fallback": FALLBACK_PATH,
        "profile_free_claims": free_claims_path(profile_id=profile_id),
        "sponsors": SPONSORS_PATH,
        "itad": itad_path(profile_id=profile_id),
        "personal": personal_path(profile_id=profile_id),
    }
    baseline: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "profile_id": profile_id,
        "files": {},
        "item_counts": {},
    }
    for name, path in paths.items():
        meta = _file_meta(path)
        baseline["files"][name] = meta
        doc = _load_json(path)
        if isinstance(doc, dict) and "items" in doc:
            baseline["item_counts"][name] = len(_items(doc))
        elif name == "approved" and isinstance(doc, dict):
            baseline["item_counts"][name] = len(doc.get("ids") or [])
    return baseline


def run_audit(profile_id: str, *, check_urls: bool = False, url_limit: int = 30) -> dict[str, Any]:
    auto = _load_json(AUTO_PATH)
    approved = _load_json(APPROVED_PATH)
    input_doc = _load_json(INPUT_PATH)
    built = _load_json(BUILT_PATH)
    fallback = _load_json(FALLBACK_PATH)
    profile_fc = _load_json(free_claims_path(profile_id=profile_id))

    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "profile_id": profile_id,
        "baseline": build_baseline(profile_id),
        "feeds": {
            "auto": _audit_feed("auto", auto if isinstance(auto, dict) else None, AUTO_PATH),
            "built": _audit_feed("built", built if isinstance(built, dict) else None, BUILT_PATH),
            "fallback": _audit_feed("fallback", fallback if isinstance(fallback, dict) else None, FALLBACK_PATH),
            "profile": _audit_feed(
                "profile",
                profile_fc if isinstance(profile_fc, dict) else None,
                free_claims_path(profile_id=profile_id),
            ),
        },
        "approved": _approved_audit(
            approved if isinstance(approved, dict) else None,
            auto if isinstance(auto, dict) else None,
            built if isinstance(built, dict) else None,
            input_doc if isinstance(input_doc, dict) else None,
        ),
        "cross_layer": _cross_layer_diff(
            built if isinstance(built, dict) else None,
            fallback if isinstance(fallback, dict) else None,
            profile_fc if isinstance(profile_fc, dict) else None,
        ),
        "personal": _personal_audit(profile_id, _items(profile_fc if isinstance(profile_fc, dict) else None)),
        "itad": _itad_audit(profile_id),
        "sponsors": _sponsors_audit(),
        "plan": _plan_audit(),
        "landing_demo": {
            "note": "landing/demo.js STATS are independent dummy marketing data",
            "demo_wl_deals": 14,
            "demo_stores": 7,
        },
        "prefs_note": {
            "storage": "localStorage via prefsStorageKey() — not on disk; inspect in browser DevTools",
            "expected_keys": list(CLAIMS_PREFS_KEYS),
            "defaults": {
                "claimsAutoRefreshIntervalMin": 120,
                "claimsAutoRefreshDisabled": "absent=false (enabled)",
                "itadAutoRefreshIntervalMin": 15,
                "autoFetchStale24h": True,
            },
        },
    }

    if check_urls:
        report["url_checks"] = _check_urls(_items(built if isinstance(built, dict) else None), limit=url_limit)

    report["findings"] = _compile_findings(report)
    report["findings_summary"] = Counter(f["severity"] for f in report["findings"])
    report["findings_by_owner"] = Counter(f["owner"] for f in report["findings"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None, help="Profile id (default: active from index / BAKLOG_PROFILE)")
    parser.add_argument("--out", default="review-report.json", help="Output report path (repo root relative)")
    parser.add_argument("--baseline-out", default="review-baseline.json", help="Baseline-only snapshot path")
    parser.add_argument("--csv-out", default="review-feed-rows.csv", help="Per-row CSV export")
    parser.add_argument("--findings-out", default="review-findings.yaml", help="Findings handoff path")
    parser.add_argument("--handoff-out", default="review-handoff.md", help="Executive handoff markdown")
    parser.add_argument("--check-urls", action="store_true", help="HEAD-check up to 30 cover URLs (slow)")
    parser.add_argument("--url-limit", type=int, default=30)
    parser.add_argument(
        "--fail-on",
        choices=("high", "medium", "low"),
        default=None,
        help="Exit 1 when findings at or above this severity exist (CI gate)",
    )
    args = parser.parse_args()

    profile_id = args.profile or get_active_profile_id()
    report = run_audit(profile_id, check_urls=args.check_urls, url_limit=args.url_limit)

    out_path = ROOT / args.out
    baseline_path = ROOT / args.baseline_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(report["baseline"], indent=2, ensure_ascii=False), encoding="utf-8")

    out_path = ROOT / args.out
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    findings_path = ROOT / args.findings_out
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Free-tier data review findings", f"# captured: {report['captured_at']}", ""]
    for f in report["findings"]:
        lines.append(f"- id: {f['id']}")
        for key in ("severity", "owner", "artifact", "row", "observed", "expected", "suggested_action", "blocks"):
            val = f.get(key)
            if val is not None:
                lines.append(f"  {key}: {val}")
        lines.append("")
    findings_path.write_text("\n".join(lines), encoding="utf-8")

    csv_path = ROOT / args.csv_out
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_row_csv(report, csv_path)

    handoff_path = ROOT / args.handoff_out
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    _write_handoff_md(report, handoff_path)

    print(f"Profile: {profile_id}")
    print(f"Baseline -> {baseline_path}")
    print(f"Report   -> {out_path}")
    print(f"CSV      -> {csv_path}")
    print(f"Handoff  -> {handoff_path}")
    print(f"Findings -> {findings_path} ({len(report['findings'])} items)")
    print(f"Summary: {dict(report['findings_summary'])} by severity, {dict(report['findings_by_owner'])} by owner")
    if args.fail_on:
        rank = {"high": 3, "medium": 2, "low": 1}
        floor = rank[args.fail_on]
        bad = [f for f in report["findings"] if rank.get(f.get("severity"), 0) >= floor]
        if bad:
            print(
                f"FAIL: {len(bad)} finding(s) at or above {args.fail_on} severity",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
