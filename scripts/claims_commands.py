#!/usr/bin/env python3
"""Apply owner checkbox commands from the claims digest issue to owner decisions.

Runs from the private repo's ``claims-commands.yml`` on ``issues: edited``. Only
boxes that flipped from ``[ ]`` to ``[x]`` between the old and new issue body
count, so the autopilot rewriting the body never triggers anything.

Commands (HTML comment markers written by ``claims_autopilot.py``):

- ``cmd:remove:<id>``    -> add to ``blocked`` (and drop from ``ids``)
- ``cmd:approve:<id>``   -> add to ``ids`` (and drop from ``dismissed`` / ``blocked``)
- ``cmd:approve-stale:<id>`` -> approve, plus an ``ends_at`` field override 14 days
  out when none is set (undated row that may be past the build's
  first_seen + 14d window by the time the box is ticked)
- ``cmd:split:<a>,<b>,…`` -> add every pair to ``dupe_splits``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_CHECKBOX_RE = re.compile(
    r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s.*<!--\s*cmd:(?P<action>remove|approve-stale|approve|split)"
    r":(?P<args>[^>\s]+)\s*-->",
)
# The commands workflow sparse-checks out scripts/ only, so this cannot import
# shared.claims_expiry; keep in step with DEFAULT_EXPIRY_DAYS there.
_APPROVE_END_DAYS = 14
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def _commands(body: str) -> dict[tuple[str, str], bool]:
    out: dict[tuple[str, str], bool] = {}
    for line in (body or "").splitlines():
        m = _CHECKBOX_RE.match(line)
        if m:
            out[(m["action"], m["args"])] = m["mark"].lower() == "x"
    return out


def newly_checked(old_body: str, new_body: str) -> list[tuple[str, list[str]]]:
    old = _commands(old_body)
    new = _commands(new_body)
    out: list[tuple[str, list[str]]] = []
    for (action, raw), checked in new.items():
        if not checked or old.get((action, raw)):
            continue
        ids = [i for i in raw.split(",") if _ID_RE.match(i)]
        if not ids:
            continue
        if action != "split":
            ids = ids[:1]
        elif len(ids) < 2:
            continue
        out.append((action, ids))
    return out


def _list(doc: dict, key: str) -> list:
    raw = doc.get(key)
    return list(raw) if isinstance(raw, list) else []


def apply_commands(
    doc: dict,
    commands: list[tuple[str, list[str]]],
    *,
    now: datetime | None = None,
) -> tuple[dict, list[str]]:
    out = dict(doc)
    now = now or datetime.now(UTC)
    ids = [str(i) for i in _list(out, "ids")]
    blocked = [str(i) for i in _list(out, "blocked")]
    dismissed = [str(i) for i in _list(out, "dismissed")]
    splits = [list(p) for p in _list(out, "dupe_splits") if isinstance(p, list)]
    seen_pairs = {tuple(sorted(p)) for p in splits if len(p) == 2}
    raw_fields = out.get("field_overrides")
    fields = {k: dict(v) for k, v in raw_fields.items()} if isinstance(raw_fields, dict) else {}
    log: list[str] = []
    for action, args in commands:
        if action == "remove":
            item = args[0]
            ids = [i for i in ids if i != item]
            if item not in blocked:
                blocked.append(item)
            log.append(f"removed {item}")
        elif action in ("approve", "approve-stale"):
            item = args[0]
            blocked = [i for i in blocked if i != item]
            dismissed = [i for i in dismissed if i != item]
            if item not in ids:
                ids.append(item)
            entry = fields.setdefault(item, {})
            if action == "approve-stale" and not str(entry.get("ends_at") or "").strip():
                end = (now + timedelta(days=_APPROVE_END_DAYS)).astimezone(UTC).replace(microsecond=0)
                entry["ends_at"] = end.isoformat().replace("+00:00", "Z")
                log.append(f"approved {item} (end date {entry['ends_at'][:10]})")
            else:
                log.append(f"approved {item}")
            if not entry:
                fields.pop(item, None)
        elif action == "split":
            members = sorted(set(args))
            for a_pos, a in enumerate(members):
                for b in members[a_pos + 1 :]:
                    if (a, b) not in seen_pairs:
                        seen_pairs.add((a, b))
                        splits.append([a, b])
            log.append(f"split {', '.join(members)}")
    out["ids"] = ids
    for key, val in (
        ("blocked", blocked),
        ("dismissed", dismissed),
        ("dupe_splits", splits),
        ("field_overrides", fields),
    ):
        if val:
            out[key] = val
        else:
            out.pop(key, None)
    return out, log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--approved", type=Path, required=True)
    parser.add_argument("--owner", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    args = parser.parse_args(argv)
    if not args.event or not Path(args.event).is_file():
        print("ERROR: no event payload", file=sys.stderr)
        return 1
    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    sender = str((event.get("sender") or {}).get("login") or "")
    if args.owner and sender.lower() != args.owner.lower():
        print(f"ignored: edit by {sender or 'unknown'}, not the owner")
        return 0
    old_body = str(((event.get("changes") or {}).get("body") or {}).get("from") or "")
    new_body = str((event.get("issue") or {}).get("body") or "")
    commands = newly_checked(old_body, new_body)
    if not commands:
        print("no new commands")
        return 0
    doc = json.loads(args.approved.read_text(encoding="utf-8")) if args.approved.is_file() else {}
    updated, log = apply_commands(doc, commands)
    args.approved.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for line in log:
        print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("applied=true\n")
            fh.write(f"summary={'; '.join(log)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
