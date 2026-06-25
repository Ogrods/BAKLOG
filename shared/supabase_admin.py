"""Maintainer-only Supabase Auth admin helpers (service_role key)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_maintainer_env() -> None:
    """Load SUPABASE_* from repo root ``.env`` then ``landing/.env`` (skip empty values)."""
    for rel in (".env", "landing/.env"):
        path = ROOT / rel
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


def admin_request(
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


def list_users(base: str, key: str) -> list[dict]:
    users: list[dict] = []
    page = 1
    while True:
        qs = urllib.parse.urlencode({"page": page, "per_page": 200})
        batch = admin_request("GET", f"{base}/auth/v1/admin/users?{qs}", key=key)
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


def find_user_by_email(base: str, key: str, email: str) -> dict | None:
    target = email.strip().lower()
    for user in list_users(base, key):
        mail = str(user.get("email") or "").strip().lower()
        if mail == target:
            return user
    return None


def invite_user_by_email(
    base: str,
    key: str,
    email: str,
    *,
    redirect_to: str,
) -> dict:
    qs = urllib.parse.urlencode({"redirect_to": redirect_to})
    result = admin_request(
        "POST",
        f"{base}/auth/v1/invite?{qs}",
        key=key,
        body={"email": email},
    )
    return result if isinstance(result, dict) else {}


def set_user_plan(base: str, key: str, user_id: str, plan: str, user: dict | None = None) -> None:
    meta = dict((user or {}).get("app_metadata") or {})
    meta["plan"] = plan
    admin_request(
        "PUT",
        f"{base}/auth/v1/admin/users/{user_id}",
        key=key,
        body={"app_metadata": meta},
    )
