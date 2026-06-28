import base64
import json
import os
import sys
import time
from pathlib import Path

import jwt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_env(path):
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val:
            out[key] = val
    return out


def _anon_ref(anon):
    try:
        payload = json.loads(base64.urlsafe_b64decode(anon.split(".")[1] + "=="))
        return str(payload.get("ref") or "")
    except Exception:
        return ""


def main():
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    install_env = local / "BAKLOG" / ".env"
    data_env = local / "BAKLOG-Data" / ".env"
    print(f"install .env: {install_env} ({('present' if install_env.is_file() else 'MISSING')})")
    print(f"data .env:    {data_env} ({('present' if data_env.is_file() else 'MISSING')})")
    data = _parse_env(data_env)
    install = _parse_env(install_env)
    url = data.get("BAKLOG_SUPABASE_URL") or install.get("BAKLOG_SUPABASE_URL") or ""
    anon = data.get("BAKLOG_SUPABASE_ANON_KEY") or install.get("BAKLOG_SUPABASE_ANON_KEY") or ""
    secret = data.get("BAKLOG_SUPABASE_JWT_SECRET") or install.get("BAKLOG_SUPABASE_JWT_SECRET") or ""
    if not url or not anon:
        print("ERROR: missing BAKLOG_SUPABASE_URL or ANON_KEY in both locations")
        return 1
    ref = _anon_ref(anon)
    host = url.rstrip("/").split("//")[-1].split(".")[0]
    print(f"supabase project ref in anon key: {ref or '(decode failed)'}")
    print(f"supabase URL host ref:            {host}")
    print(f"ref matches URL:                  {ref == host}")
    print(f"jwt_secret present:               {bool(secret)} (len {len(secret)})")
    try:
        import urllib.request

        jwks_url = f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        with urllib.request.urlopen(jwks_url, timeout=10) as resp:
            jwks = json.loads(resp.read())
        print(f"JWKS fetch:                       OK ({len(jwks.get('keys', []))} key(s))")
    except Exception as exc:
        print(f"JWKS fetch:                       FAIL ({exc})")
    if secret:
        os.environ["BAKLOG_SUPABASE_URL"] = url
        os.environ["BAKLOG_SUPABASE_ANON_KEY"] = anon
        os.environ["BAKLOG_SUPABASE_JWT_SECRET"] = secret
        from shared import supabase_auth

        supabase_auth.reset_jwks_client_for_tests()
        iss = f"{url.rstrip('/')}/auth/v1"
        raw = jwt.encode(
            {
                "sub": "550e8400-e29b-41d4-a716-446655440000",
                "aud": "authenticated",
                "iss": iss,
                "exp": int(time.time()) + 3600,
            },
            secret,
            algorithm="HS256",
        )
        ok = supabase_auth.verify_bearer_user(f"Bearer {raw}") is not None
        print(f"HS256 test token verify:          {('OK' if ok else 'FAIL')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
