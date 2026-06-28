"""Grant or revoke BAKLOG Pro on hosted Supabase accounts (maintainer one-off).

Uses the GoTrue admin API to set ``app_metadata.plan`` on each user. Safe by
default: prints the plan and exits unless ``--apply`` is passed.

Env (shell or repo ``.env``):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Examples:
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --email you@example.com --apply
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --before 2026-07-01 --apply
  .\\.venv\\Scripts\\python.exe scripts\\grant_beta_pro.py --plan free --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from shared.supabase_admin import admin_request, list_users, load_maintainer_env

PRO_ALIASES = frozenset({"pro", "paid", "premium"})


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
    parser.add_argument("--limit", type=int, default=0, help="Max users to touch (0 = no cap).")
    args = parser.parse_args(argv)

    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 2

    cutoff = None
    if args.before:
        cutoff = datetime.fromisoformat(args.before).replace(tzinfo=UTC)

    target_plan = _normalize_plan(args.plan)
    users = list_users(url, key)
    email_filter = (args.email or "").strip().lower()
    selected: list[dict] = []
    for user in users:
        mail = str(user.get("email") or "").strip().lower()
        if email_filter and mail != email_filter:
            continue
        if not _created_before(user, cutoff):
            continue
        selected.append(user)
        if args.limit and len(selected) >= args.limit:
            break

    if not selected:
        print("No matching users.")
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: set plan={target_plan!r} on {len(selected)} user(s)")
    changed = 0
    for user in selected:
        uid = user.get("id") or user.get("user_id")
        mail = user.get("email") or "(no email)"
        meta = dict(user.get("app_metadata") or {})
        prev = meta.get("plan", "free")
        meta["plan"] = target_plan
        print(f"  {mail}  {prev!r} -> {target_plan!r}  ({uid})")
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
