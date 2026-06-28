import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_KEYS = ("BAKLOG_SUPABASE_URL", "BAKLOG_SUPABASE_ANON_KEY", "BAKLOG_SUPABASE_JWT_SECRET", "BAKLOG_LOCAL_PROFILES")
REQUIRED_KEYS = ("BAKLOG_SUPABASE_URL", "BAKLOG_SUPABASE_ANON_KEY")


def _parse_env_file(path):
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


def collect_auth_env():
    merged = {}
    for path in (ROOT / "packaging" / "bundle-auth.env", ROOT / ".env"):
        for key, val in _parse_env_file(path).items():
            if key in BUNDLE_KEYS and key not in merged:
                merged[key] = val
    for key in BUNDLE_KEYS:
        if key not in merged:
            raw = (os.environ.get(key) or "").strip()
            if raw:
                merged[key] = raw
    return merged


def render_env_lines(values):
    lines = [
        "# BAKLOG account auth (bundled for beta builds).",
        "# Anon key is public; included so the local app can require sign-in.",
    ]
    for key in BUNDLE_KEYS:
        if key in values:
            lines.append(f"{key}={values[key]}")
    return lines


def main(argv=None):
    args = list(argv or sys.argv[1:])
    if not args:
        print("Usage: write_bundle_auth_env.py <bundle-out-dir>", file=sys.stderr)
        return 2
    out_dir = Path(args[0]).resolve()
    values = collect_auth_env()
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    if missing:
        print(
            "Missing auth env for frozen bundle: "
            + ", ".join(missing)
            + ". Set them in packaging/bundle-auth.env, repo .env, or CI env.",
            file=sys.stderr,
        )
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / ".env"
    dest.write_text("\n".join(render_env_lines(values)) + "\n", encoding="utf-8")
    print(f"Wrote {dest} ({len(values)} auth key(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
