from __future__ import annotations
import os
from pathlib import Path
from shared.supabase_admin import admin_request, load_maintainer_env
ROOT = Path(__file__).resolve().parents[1]
COMP_PRO_EMAILS_PATH = ROOT / 'packaging' / 'pro_invitees.txt'
PRO_ALIASES = frozenset({'pro', 'paid', 'premium'})

def load_comp_pro_emails(path: Path | None=None) -> frozenset[str]:
    target = path or COMP_PRO_EMAILS_PATH
    if not target.is_file():
        return frozenset()
    emails: set[str] = set()
    for line in target.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '@' in line:
            emails.add(line.lower())
    return frozenset(emails)

def is_comp_pro_email(email: str, *, comp_emails: frozenset[str] | None=None) -> bool:
    listed = comp_emails if comp_emails is not None else load_comp_pro_emails()
    return email.strip().lower() in listed

def _admin_creds() -> tuple[str, str] | None:
    load_maintainer_env()
    base = (os.environ.get('SUPABASE_URL') or '').strip().rstrip('/')
    key = (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    if not base or not key:
        return None
    return (base, key)

def _user_plan(meta: dict | None) -> str:
    if not isinstance(meta, dict):
        return 'free'
    plan = str(meta.get('plan') or 'free').strip().lower()
    return 'pro' if plan in PRO_ALIASES else 'free'

def ensure_comp_pro_on_login(user_id: str, email: str) -> tuple[bool, bool]:
    if not is_comp_pro_email(email):
        return (False, False)
    creds = _admin_creds()
    if not creds:
        return (True, False)
    base, key = creds
    uid = (user_id or '').strip()
    if not uid:
        return (True, False)
    try:
        user = admin_request('GET', f'{base}/auth/v1/admin/users/{uid}', key=key)
    except RuntimeError:
        return (True, False)
    if not isinstance(user, dict):
        return (True, False)
    meta = dict(user.get('app_metadata') or {})
    if _user_plan(meta) == 'pro':
        return (True, False)
    meta['plan'] = 'pro'
    try:
        admin_request('PUT', f'{base}/auth/v1/admin/users/{uid}', key=key, body={'app_metadata': meta})
    except RuntimeError:
        return (True, False)
    return (True, True)
load_pro_invite_emails = load_comp_pro_emails

def should_grant_pro(email: str, *, explicit: bool, pro_invitees: frozenset[str] | None=None) -> bool:
    if explicit:
        return True
    listed = pro_invitees if pro_invitees is not None else load_comp_pro_emails()
    return email.strip().lower() in listed