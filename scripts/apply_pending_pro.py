"""Link a Polar purchase made with a different email to a BAKLOG account (maintainer one-off).

When a buyer pays with an email that has no BAKLOG account, polar-webhook.js stores
the purchase in ``polar_pending_entitlements`` and emails the founder. If the
buyer's account uses another email, run this to move the purchase onto it.

Marks the account paid the same way the webhook does (``plan=pro``, ``paid``,
``paid_since`` on first payment) so the daily comp-expire cron never drops it,
then stamps the pending row applied. Safe by default: dry run unless ``--apply``.

Env (shell or repo ``.env``): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

Example:
  .\\.venv\\Scripts\\python.exe scripts\\apply_pending_pro.py --email buyer@example.com --to account@example.com
  .\\.venv\\Scripts\\python.exe scripts\\apply_pending_pro.py --email buyer@example.com --to account@example.com --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.supabase_admin import admin_request, find_user_by_email, load_maintainer_env  # noqa: E402

TABLE = "polar_pending_entitlements"


def _now() -> datetime:
    return datetime.now(UTC)


def paid_pro_metadata(meta: dict, today: str) -> dict:
    """Same transition as applyPaidEntitlement(meta, "pro") in web/api/_polar-pending.js."""
    out = dict(meta)
    if not out.get("paid") or not str(out.get("paid_since") or "").strip():
        out["paid_since"] = today
    out["paid"] = True
    out["plan"] = "pro"
    return out


def _pending_row(url: str, key: str, email: str) -> dict | None:
    qs = urllib.parse.urlencode({"email": f"eq.{email}", "select": "*", "limit": "1"})
    rows = admin_request("GET", f"{url}/rest/v1/{TABLE}?{qs}", key=key)
    return rows[0] if isinstance(rows, list) and rows else None


def main(argv: list[str] | None = None) -> int:
    load_maintainer_env()
    parser = argparse.ArgumentParser(description="Apply a pending Polar Pro purchase to a different account email.")
    parser.add_argument("--email", required=True, help="Email the buyer used at Polar checkout.")
    parser.add_argument("--to", required=True, dest="to_email", help="Email of the BAKLOG account to upgrade.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed without a pending pro row (buyer contacted you directly).",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run).")
    args = parser.parse_args(argv)

    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 2

    buyer = args.email.strip().lower()
    pending = _pending_row(url, key, buyer)
    if pending is None and not args.force:
        print(f"No pending purchase for {buyer}. Use --force if the buyer contacted you directly.", file=sys.stderr)
        return 1
    if pending is not None:
        if str(pending.get("plan") or "") != "pro":
            print(f"Pending row for {buyer} is plan={pending.get('plan')!r} (cancelled or refunded).", file=sys.stderr)
            return 1
        if pending.get("applied_at"):
            print(f"Pending row for {buyer} was already applied at {pending['applied_at']}.", file=sys.stderr)
            return 1

    user = find_user_by_email(url, key, args.to_email)
    if not user:
        print(f"No BAKLOG account for {args.to_email}.", file=sys.stderr)
        return 1
    uid = str(user.get("id") or "")
    before = dict(user.get("app_metadata") or {})
    now = _now()
    after = paid_pro_metadata(before, now.date().isoformat())

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: {buyer} purchase -> {user.get('email')} ({uid})")
    print(f"  before: {before}")
    print(f"  after:  {after}")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write.")
        return 0

    admin_request("PUT", f"{url}/auth/v1/admin/users/{uid}", key=key, body={"app_metadata": after})
    if pending is not None:
        stamp = now.isoformat()
        qs = urllib.parse.urlencode({"email": f"eq.{buyer}"})
        admin_request(
            "PATCH",
            f"{url}/rest/v1/{TABLE}?{qs}",
            key=key,
            body={"applied_at": stamp, "applied_user_id": uid, "updated_at": stamp},
        )
    print("Done. Ask them to click Refresh Pro status or sign in again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
