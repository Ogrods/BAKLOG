from __future__ import annotations
import argparse
import os
import sys
from shared.comp_pro import should_grant_pro
from shared.supabase_admin import find_user_by_email, invite_user_by_email, load_maintainer_env, set_user_plan
DEFAULT_REDIRECT = 'https://baklog.app/auth/reset'

def main(argv: list[str] | None=None) -> int:
    load_maintainer_env()
    parser = argparse.ArgumentParser(description='Invite a hosted BAKLOG user via Supabase Auth.')
    parser.add_argument('--email', required=True, help='Account email (case-insensitive).')
    parser.add_argument('--send', action='store_true', help='Send the Supabase invite email.')
    parser.add_argument('--redirect-to', default=DEFAULT_REDIRECT, help=f'Invite link redirect URL (default: {DEFAULT_REDIRECT}).')
    parser.add_argument('--grant-pro', action='store_true', help='Also set plan=pro on invite (listed emails get Pro on login anyway).')
    parser.add_argument('--no-list-pro', action='store_true', help='Ignore pro_invitees.txt for this invite only.')
    args = parser.parse_args(argv)
    base = (os.environ.get('SUPABASE_URL') or '').strip().rstrip('/')
    key = (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    if not base or not key:
        print('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.', file=sys.stderr)
        return 2
    email = args.email.strip()
    if not email or '@' not in email:
        print('Provide a valid --email.', file=sys.stderr)
        return 2
    redirect_to = (args.redirect_to or DEFAULT_REDIRECT).strip()
    grant_pro = should_grant_pro(email, explicit=args.grant_pro, pro_invitees=frozenset() if args.no_list_pro else None)
    grant_note = ''
    if grant_pro and (not args.grant_pro) and (not args.no_list_pro):
        from shared.comp_pro import is_comp_pro_email
        if is_comp_pro_email(email):
            grant_note = ' (pro_invitees.txt)'
    existing = find_user_by_email(base, key, email)
    mode = 'SEND' if args.send else 'DRY-RUN'
    if existing:
        uid = str(existing.get('id') or existing.get('user_id') or '')
        print(f"{mode}: {email} already registered ({uid or 'no id'})")
        if grant_pro:
            prev = (existing.get('app_metadata') or {}).get('plan', 'free')
            print(f"  grant-pro{grant_note}: {prev!r} -> 'pro'")
            if args.send and uid:
                set_user_plan(base, key, uid, 'pro', existing)
                print('  Updated plan to pro.')
        elif not args.send:
            print('Dry-run only. Re-run with --send to apply.')
        return 0
    print(f'{mode}: invite {email!r} redirect_to={redirect_to!r}')
    if grant_pro:
        print(f'  grant-pro{grant_note}: will set plan=pro after invite')
    if not args.send:
        print('Dry-run only. Re-run with --send to email the invite.')
        return 0
    invited = invite_user_by_email(base, key, email, redirect_to=redirect_to)
    uid = str(invited.get('id') or '')
    print(f"Invited {email} ({uid or 'id pending'})")
    if grant_pro and uid:
        set_user_plan(base, key, uid, 'pro', invited)
        print(f'Set plan=pro on invited user{grant_note}.')
    print('They should receive a Supabase email to set a password, then sign in to BAKLOG.')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())