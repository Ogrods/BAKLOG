#!/usr/bin/env python3
"""Claims autopilot: classify the inbox, write auto decisions, render a digest.

Subcommands:

``run``
    Group dupes + apply ``shared/claims_policy`` to ``curated/free_claims.auto.json``
    under owner decisions, write ``auto_decisions.json`` and a digest (markdown with
    command checkboxes + JSON). Sets ``changed=true|false`` in ``$GITHUB_OUTPUT``.

``verify-added``
    Auto-merge gate: every id added to the published feed must be owner-approved or
    autopilot-approved. Exit 0 = safe to auto-merge, 3 = needs a human.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.claims_decisions import (  # noqa: E402
    AUTO_DECISIONS_VERSION,
    load_auto_decisions,
    scoped_match_keys,
)
from shared.claims_dedupe import group_claims  # noqa: E402
from shared.claims_expiry import has_ends_at, is_trusted_live_listing  # noqa: E402
from shared.claims_paths import resolve_approved_path, resolve_auto_decisions_path  # noqa: E402
from shared.claims_policy import (  # noqa: E402
    AUTO_PUBLISH,
    DISMISS_DUPE,
    REVIEW,
    Classification,
    OwnerState,
    classify_inbox,
)
from shared.free_claims_sources import norm_title  # noqa: E402

DIGEST_MARKER = "<!-- baklog-claims-digest -->"
_COVER_STOPWORDS = {"a", "an", "and", "the", "of"}


def _cover_key(title: str) -> str:
    """Same key admin ``coverLookupKey`` writes into owner ``dismissed_keys``."""
    return " ".join(w for w in norm_title(title).split() if w not in _COVER_STOPWORDS)


def _read_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _id_set(doc: dict, key: str) -> set[str]:
    raw = doc.get(key)
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def owner_state_from_doc(doc: dict, items: list[dict]) -> OwnerState:
    dismissed_keys = _id_set(doc, "dismissed_keys")
    by_key = {
        str(it.get("id") or "").strip()
        for it in items
        if dismissed_keys and _cover_key(str(it.get("title") or "")) in dismissed_keys
    }
    return OwnerState(
        approved=_id_set(doc, "ids"),
        dismissed=_id_set(doc, "dismissed"),
        blocked=_id_set(doc, "blocked"),
        dismissed_item_ids={i for i in by_key if i},
        premium_only=_id_set(doc, "premium_only_ids"),
    )


def _dupe_match_keys(results: list[Classification], by_id: dict[str, dict]) -> list[str]:
    keys: set[str] = set()
    for c in results:
        if c.action != DISMISS_DUPE or c.id not in by_id:
            continue
        loser_keys = scoped_match_keys(by_id[c.id])
        keeper = by_id.get(c.keeper_id or "")
        if keeper is not None:
            loser_keys -= scoped_match_keys(keeper)
        keys |= loser_keys
    return sorted(keys)


def build_decisions(
    results: list[Classification],
    items: list[dict],
    prior: dict,
    *,
    now: datetime,
) -> dict:
    by_id = {str(it.get("id") or "").strip(): it for it in items}
    prior_meta = prior.get("decisions") if isinstance(prior.get("decisions"), dict) else {}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    decisions: dict[str, dict] = {}
    for c in results:
        if c.action not in (AUTO_PUBLISH, DISMISS_DUPE, REVIEW):
            continue
        item = by_id.get(c.id, {})
        prev = prior_meta.get(c.id) if isinstance(prior_meta.get(c.id), dict) else {}
        same = prev.get("action") == c.action
        decisions[c.id] = {
            "action": c.action,
            "reason": c.reason,
            "keeper": c.keeper_id,
            "title": str(item.get("title") or ""),
            "source": str(item.get("source") or ""),
            "store": str(item.get("store") or ""),
            "at": prev.get("at") if same and prev.get("at") else stamp,
        }
    return {
        "version": AUTO_DECISIONS_VERSION,
        "updated_at": stamp,
        "approve": sorted(c.id for c in results if c.action == AUTO_PUBLISH),
        "dismiss": sorted(c.id for c in results if c.action == DISMISS_DUPE),
        "dismissed_match_keys": _dupe_match_keys(results, by_id),
        "decisions": dict(sorted(decisions.items())),
    }


def diff_decisions(prior: dict, new: dict) -> dict[str, list[str]]:
    p_meta = prior.get("decisions") if isinstance(prior.get("decisions"), dict) else {}
    new_review = sorted(
        i for i, d in new["decisions"].items()
        if d["action"] == REVIEW and (p_meta.get(i) or {}).get("action") != REVIEW
    )
    return {
        "approved_added": sorted(set(new["approve"]) - set(prior.get("approve") or [])),
        "approved_removed": sorted(set(prior.get("approve") or []) - set(new["approve"])),
        "dismissed_added": sorted(set(new["dismiss"]) - set(prior.get("dismiss") or [])),
        "review_added": new_review,
    }


def has_changes(diff: dict[str, list[str]]) -> bool:
    return any(diff.values())


def _ends(item: dict) -> str:
    raw = str(item.get("ends_at") or "")
    return f", ends {raw[:10]}" if raw else ""


def _line(item: dict) -> str:
    title = str(item.get("title") or item.get("id") or "").replace("|", "/")
    src = str(item.get("source") or "?")
    store = str(item.get("store") or "?")
    url = str(item.get("claim_url") or "")
    link = f" [link]({url})" if url.startswith(("http://", "https://")) else ""
    return f"**{title}** ({src}, {store}{_ends(item)}){link}"


def render_digest(
    results: list[Classification],
    items: list[dict],
    diff: dict[str, list[str]],
    *,
    now: datetime,
    owner_approved: set[str] | None = None,
) -> str:
    by_id = {str(it.get("id") or "").strip(): it for it in items}
    owner_approved = owner_approved or set()
    auto = [c for c in results if c.action == AUTO_PUBLISH]
    review = [c for c in results if c.action == REVIEW]
    dupes: dict[str, list[Classification]] = {}
    for c in results:
        if c.action == DISMISS_DUPE and c.keeper_id:
            dupes.setdefault(c.keeper_id, []).append(c)

    lines = [
        DIGEST_MARKER,
        "# Free claims autopilot",
        "",
        f"_Updated {now.strftime('%Y-%m-%d %H:%M UTC')}. Tick a box to act; "
        "the claims-commands workflow applies it and re-runs ingest._",
        "",
        f"- Auto-published: **{len(auto)}** (new this run: {len(diff['approved_added'])})",
        f"- Dupes merged: **{sum(len(v) for v in dupes.values())}** rows into {len(dupes)} keepers",
        f"- Needs review: **{len(review)}** (new this run: {len(diff['review_added'])})",
        f"- Owner-approved live: **{len(owner_approved)}**",
        "",
        "## Auto-published",
        "",
    ]
    if not auto:
        lines.append("- (none)")
    for c in auto:
        new = " (new)" if c.id in diff["approved_added"] else ""
        lines.append(
            f"- [ ] Remove: {_line(by_id[c.id])}{new} <sub>{c.reason}</sub> "
            f"<!-- cmd:remove:{c.id} -->"
        )
    lines += ["", "## Dupes merged", ""]
    if not dupes:
        lines.append("- (none)")
    for keeper_id, losers in sorted(dupes.items()):
        keeper = by_id.get(keeper_id, {"id": keeper_id})
        hidden = ", ".join(f"`{c.id}`" for c in losers)
        members = ",".join([keeper_id, *(c.id for c in losers)])
        lines.append(
            f"- [ ] Not a dupe: kept {_line(keeper)}, hid {hidden} <!-- cmd:split:{members} -->"
        )
    lines += ["", "## Needs review", ""]
    if not review:
        lines.append("- (none)")
    for c in review:
        new = " (new)" if c.id in diff["review_added"] else ""
        # Decided at tick time by claims_commands, which has no feed rows: any
        # undated row that is not a live listing may cross first_seen + 14d first.
        row = by_id[c.id]
        undated_unlisted = not has_ends_at(row) and not is_trusted_live_listing(row, now)
        action = "approve-stale" if undated_unlisted else "approve"
        lines.append(
            f"- [ ] Approve: {_line(by_id[c.id])}{new} <sub>{c.reason}</sub> "
            f"<!-- cmd:{action}:{c.id} -->"
        )
    lines.append("")
    return "\n".join(lines)


def _set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def cmd_run(args: argparse.Namespace) -> int:
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(UTC)
    )
    auto_doc = _read_json(args.auto)
    items = [it for it in (auto_doc.get("items") or []) if isinstance(it, dict)]
    approved_path = args.approved or resolve_approved_path(ROOT)
    decisions_path = args.decisions or resolve_auto_decisions_path(ROOT)
    if decisions_path is None:
        print("ERROR: no auto_decisions path (pass --decisions)", file=sys.stderr)
        return 1
    owner_doc = _read_json(approved_path)
    owner = owner_state_from_doc(owner_doc, items)
    splits = owner_doc.get("dupe_splits") if isinstance(owner_doc.get("dupe_splits"), list) else []
    groups = group_claims(items, splits=splits)
    results = classify_inbox(items, owner, now=now, groups=groups)
    prior = load_auto_decisions(decisions_path)
    new = build_decisions(results, items, prior, now=now)
    diff = diff_decisions(prior, new)
    changed = has_changes(diff)
    digest = render_digest(results, items, diff, now=now, owner_approved=owner.approved)

    if not args.dry_run:
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        if changed or not decisions_path.is_file():
            decisions_path.write_text(
                json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    if args.digest_md:
        args.digest_md.write_text(digest, encoding="utf-8")
    if args.digest_json:
        summary = {
            "changed": changed,
            "diff": diff,
            "counts": {
                "items": len(items),
                "auto_publish": len(new["approve"]),
                "dismiss_dupe": len(new["dismiss"]),
                "review": sum(1 for c in results if c.action == REVIEW),
                "groups": sum(1 for g in groups if g.tier == "strong"),
                "possible_groups": sum(1 for g in groups if g.tier == "possible"),
            },
        }
        args.digest_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        f"autopilot: {len(new['approve'])} auto-publish, {len(new['dismiss'])} dupes, "
        f"{sum(1 for c in results if c.action == REVIEW)} review; changed={changed}"
    )
    _set_output("changed", "true" if changed else "false")
    return 0


def cmd_verify_added(args: argparse.Namespace) -> int:
    before = {str(it.get("id")) for it in _read_json(args.before).get("items") or [] if isinstance(it, dict)}
    after_items = [it for it in _read_json(args.after).get("items") or [] if isinstance(it, dict)]
    added = sorted({str(it.get("id")) for it in after_items} - before)
    allowed = _id_set(_read_json(args.approved), "ids") | set(
        load_auto_decisions(args.decisions).get("approve") or []
    )
    manual_ids = {
        str(it.get("id")) for it in _read_json(args.manual).get("items") or [] if isinstance(it, dict)
    } if args.manual else set()
    unvetted = [i for i in added if i not in allowed and i not in manual_ids]
    print(f"added {len(added)}; unvetted {len(unvetted)}")
    for i in unvetted:
        print(f"  unvetted: {i}")
    _set_output("unvetted", str(len(unvetted)))
    return 3 if unvetted else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--auto", type=Path, default=ROOT / "curated" / "free_claims.auto.json")
    run.add_argument("--approved", type=Path, default=None)
    run.add_argument("--decisions", type=Path, default=None)
    run.add_argument("--digest-md", type=Path, default=None)
    run.add_argument("--digest-json", type=Path, default=None)
    run.add_argument("--now", default=None, help="ISO timestamp override (tests)")
    run.add_argument("--dry-run", action="store_true", help="Do not write auto_decisions.json")
    run.set_defaults(func=cmd_run)

    ver = sub.add_parser("verify-added")
    ver.add_argument("--before", type=Path, required=True)
    ver.add_argument("--after", type=Path, required=True)
    ver.add_argument("--approved", type=Path, required=True)
    ver.add_argument("--decisions", type=Path, required=True)
    ver.add_argument("--manual", type=Path, default=None, help="Manual input feed (always vetted)")
    ver.set_defaults(func=cmd_verify_added)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
