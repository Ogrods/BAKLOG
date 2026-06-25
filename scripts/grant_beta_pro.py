"""Grant or revoke BAKLOG Pro on hosted Supabase accounts (maintainer one-off).

Uses the GoTrue admin API to set ``app_metadata.plan`` on each user. Safe by
default: prints the plan and exits unless ``--apply`` is passed.

Env (shell or landing/.env):
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
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRO_ALIASES = frozenset({"pro", "paid", "premium"})


def _load_dotenv() -> None:
    for rel in ("landing/.env", ".env"):
        path = ROOT / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")


def _request(
    method: str,
    url: str,
    *,
    key: str,
    body: dict | None = None,
) -> dict | list:
    data = None
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc


def _list_users(base: str, key: str) -> list[dict]:
    users: list[dict] = []
    page = 1
    while True:
        qs = urllib.parse.urlencode({"page": page, "per_page": 200})
        batch = _request("GET", f"{base}/auth/v1/admin/users?{qs}", key=key)
        if not isinstance(batch, dict):
            break
        chunk = batch.get("users") or []
        if not chunk:
            break
        users.extend(chunk)
        if len(chunk) < 200:
            break
        page += 1
    return users


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
    _load_dotenv()
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
        cutoff = datetime.fromisoformat(args.before).replace(tzinfo=timezone.utc)

    target_plan = _normalize_plan(args.plan)
    users = _list_users(url, key)
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
            _request(
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
