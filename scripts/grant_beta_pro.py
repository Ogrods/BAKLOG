"""Grant or revoke BAKLOG Pro on hosted Supabase accounts (maintainer one-off).

Uses the GoTrue admin API to set ``app_metadata.plan`` on each user. Safe by
default: prints the plan and exits unless ``--apply`` is passed.

Comp grants can carry an end date (``--until``), stored as
``app_metadata.comp_until``. The daily Vercel cron (``web/api/comp-expire.js``)
is the primary expiry path; ``--expire`` is the manual fallback with the same
rule: ``plan=free`` only on accounts whose ``comp_until`` has passed, so paying
users (``paid`` set by the Polar webhook, or no ``comp_until``) and longer
grants are never touched.

Env (shell or repo ``.env``):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Examples:
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --email you@example.com --apply
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --before 2026-07-01 --until 2027-03-31 --apply
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --until 2027-03-31 --skip-pro --exclude you@example.com
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --expire --apply
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --plan free --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.supabase_admin import admin_request, list_users, load_maintainer_env  # noqa: E402

PRO_ALIASES = frozenset({"pro", "paid", "premium"})
COMP_UNTIL_KEY = "comp_until"
PAID_KEY = "paid"


def _normalize_plan(raw: str) -> str:
    val = (raw or "").strip().lower()
    if val in PRO_ALIASES:
        return "pro"
    return "free"


def _created_before(user: dict, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    created_raw = user.get("created_at") or user.get("createdAt") or ""
    try:
        created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return created <= cutoff


def _today() -> date:
    return datetime.now(UTC).date()


def _comp_expired(meta: dict, today: date) -> bool:
    if meta.get(PAID_KEY):
        return False
    raw = str(meta.get(COMP_UNTIL_KEY) or "").strip()
    if not raw:
        return False
    try:
        until = date.fromisoformat(raw[:10])
    except ValueError:
        return False
    return until < today


def _parse_until(raw: str | None) -> str | None:
    if not raw:
        return None
    return date.fromisoformat(raw.strip()).isoformat()


def main(argv: list[str] | None = None) -> int:
    load_maintainer_env()
    parser = argparse.ArgumentParser(description="Grant or revoke hosted BAKLOG Pro via Supabase admin.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--plan", default="pro", choices=("pro", "free"), help="Plan to set (default: pro).")
    parser.add_argument("--email", help="Only touch this account email (case-insensitive).")
    parser.add_argument(
        "--before",
        metavar="ISO-DATE",
        help="Only users created on or before this UTC date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        metavar="ISO-DATE",
        help="Comp end date stored as app_metadata.comp_until (with --plan pro).",
    )
    parser.add_argument(
        "--expire",
        action="store_true",
        help="Set plan=free only where comp_until is before today (UTC); ignores --plan.",
    )
    parser.add_argument(
        "--skip-pro",
        action="store_true",
        help="Skip accounts already on plan=pro (owner, existing comps, payers).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="EMAIL",
        help="Skip this account email (repeatable, case-insensitive).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max users to touch (0 = no cap).")
    args = parser.parse_args(argv)

    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 2

    try:
        until = _parse_until(args.until)
    except ValueError:
        print(f"Invalid --until date: {args.until!r} (use YYYY-MM-DD).", file=sys.stderr)
        return 2
    target_plan = "free" if args.expire else _normalize_plan(args.plan)
    if until and (args.expire or target_plan != "pro"):
        print("--until only applies when granting Pro.", file=sys.stderr)
        return 2

    cutoff = None
    if args.before:
        cutoff = datetime.fromisoformat(args.before).replace(tzinfo=UTC)

    today = _today()
    users = list_users(url, key)
    email_filter = (args.email or "").strip().lower()
    excluded = {e.strip().lower() for e in args.exclude if e.strip()}
    selected: list[dict] = []
    for user in users:
        mail = str(user.get("email") or "").strip().lower()
        meta = dict(user.get("app_metadata") or {})
        if email_filter and mail != email_filter:
            continue
        if mail in excluded:
            continue
        if not _created_before(user, cutoff):
            continue
        if args.skip_pro and _normalize_plan(str(meta.get("plan") or "")) == "pro":
            continue
        if args.expire and not _comp_expired(meta, today):
            continue
        selected.append(user)
        if args.limit and len(selected) >= args.limit:
            break

    if not selected:
        print("No matching users.")
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    suffix = f" until {until}" if until else ""
    print(f"{mode}: set plan={target_plan!r}{suffix} on {len(selected)} user(s)")
    changed = 0
    for user in selected:
        uid = user.get("id") or user.get("user_id")
        mail = user.get("email") or "(no email)"
        meta = dict(user.get("app_metadata") or {})
        prev = meta.get("plan", "free")
        prev_until = meta.get(COMP_UNTIL_KEY)
        meta["plan"] = target_plan
        if target_plan == "pro" and until:
            meta[COMP_UNTIL_KEY] = until
        elif target_plan == "free":
            meta.pop(COMP_UNTIL_KEY, None)
        until_note = f"  comp_until {prev_until!r} -> {meta.get(COMP_UNTIL_KEY)!r}" if prev_until or until else ""
        print(f"  {mail}  {prev!r} -> {target_plan!r}{until_note}  ({uid})")
        if args.apply and uid:
            admin_request(
                "PUT",
                f"{url}/auth/v1/admin/users/{uid}",
                key=key,
                body={"app_metadata": meta},
            )
            changed += 1

    if args.apply:
        print(f"Updated {changed} user(s). Ask them to Refresh Pro status or sign in again.")
    else:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
