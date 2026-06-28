import argparse
import os
import sys

from shared.comp_pro import load_comp_pro_emails
from shared.supabase_admin import (
    create_user_by_email,
    delete_user_by_email,
    find_user_by_email,
    load_maintainer_env,
    set_user_plan,
)

PRO_ALIASES = frozenset({"pro", "paid", "premium"})


def _is_pro(user):
    plan = str((user.get("app_metadata") or {}).get("plan") or "free").strip().lower()
    return plan in PRO_ALIASES


def provision_email(base, key, email, *, apply):
    target = email.strip()
    if not target or "@" not in target:
        raise ValueError(f"invalid email: {email!r}")
    existing = find_user_by_email(base, key, target)
    if existing:
        uid = str(existing.get("id") or existing.get("user_id") or "")
        if _is_pro(existing):
            print(f"  {target}  already pro  ({uid or 'no id'})")
            return "already_pro"
        print(f"  {target}  upgrade -> pro  ({uid or 'no id'})")
        if apply and uid:
            set_user_plan(base, key, uid, "pro", existing)
        return "upgraded"
    print(f"  {target}  create + plan=pro")
    if apply:
        created = create_user_by_email(base, key, target, plan="pro", email_confirm=True)
        uid = str(created.get("id") or "")
        print(f"    created ({uid or 'id pending'})")
        return "created"
    return "dry_run_create"


def main(argv=None):
    load_maintainer_env()
    parser = argparse.ArgumentParser(description="Pre-create hosted BAKLOG users with plan=pro (no email).")
    parser.add_argument("--apply", action="store_true", help="Write changes (default dry-run).")
    parser.add_argument("--email", help="Single account email.")
    parser.add_argument(
        "--from-invitees", action="store_true", help="Provision every address in packaging/pro_invitees.txt."
    )
    parser.add_argument(
        "--delete", action="store_true", help="Delete listed user(s) so Create account works again (requires --apply)."
    )
    args = parser.parse_args(argv)
    base = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not base or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 2
    emails = []
    if args.from_invitees:
        emails.extend(sorted(load_comp_pro_emails()))
    if args.email:
        emails.append(args.email.strip().lower())
    emails = sorted({e.strip().lower() for e in emails if e.strip() and "@" in e})
    if not emails:
        print("Provide --email and/or --from-invitees.", file=sys.stderr)
        return 2
    if args.delete:
        if not args.apply:
            print("--delete requires --apply.", file=sys.stderr)
            return 2
        print(f"DELETE: remove {len(emails)} user(s) from Supabase Auth")
        removed = 0
        for mail in emails:
            if delete_user_by_email(base, key, mail):
                print(f"  deleted {mail}")
                removed += 1
            else:
                print(f"  {mail}  (not found)")
        print(f"Done: deleted {removed} user(s). They can use Create account again.")
        return 0
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: provision plan=pro for {len(emails)} email(s)")
    counts = {"created": 0, "upgraded": 0, "already_pro": 0, "dry_run_create": 0}
    for mail in emails:
        try:
            action = provision_email(base, key, mail, apply=args.apply)
        except ValueError as exc:
            print(f"  skip: {exc}", file=sys.stderr)
            continue
        counts[action] = counts.get(action, 0) + 1
    if args.apply:
        print(f"Done: created={counts['created']} upgraded={counts['upgraded']} already_pro={counts['already_pro']}")
        print("Tell users: Forgot password once, then Sign in (not Create account).")
    else:
        print(f"Dry-run: would create {counts['dry_run_create']} new user(s). Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
