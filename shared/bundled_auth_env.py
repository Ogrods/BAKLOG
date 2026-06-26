"""Shipped Supabase auth env beside the frozen exe vs writable data dir."""

from __future__ import annotations

import os
from pathlib import Path

AUTH_ENV_KEYS = (
    "BAKLOG_SUPABASE_URL",
    "BAKLOG_SUPABASE_ANON_KEY",
    "BAKLOG_SUPABASE_JWT_SECRET",
    "BAKLOG_LOCAL_PROFILES",
)


def parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
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


def render_env_lines(values: dict[str, str]) -> list[str]:
    lines = [
        "# BAKLOG account auth (data dir).",
        "# Anon key is public; included so the local app can require sign-in.",
    ]
    for key in AUTH_ENV_KEYS:
        if key in values:
            lines.append(f"{key}={values[key]}")
    return lines


def sync_bundled_auth_env_to_data_dir(install_dir: Path, data_dir: Path) -> bool:
    """Fill missing auth keys in data_dir/.env from install_dir/.env (in-place upgrades)."""
    src = install_dir / ".env"
    if not src.is_file():
        return False
    bundled = parse_env_file(src)
    if not bundled.get("BAKLOG_SUPABASE_URL") or not bundled.get("BAKLOG_SUPABASE_ANON_KEY"):
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / ".env"
    merged = parse_env_file(dest)
    changed = False
    for key in AUTH_ENV_KEYS:
        if merged.get(key):
            continue
        val = bundled.get(key)
        if val:
            merged[key] = val
            changed = True
    if not changed and dest.is_file():
        return False
    if not merged:
        return False
    dest.write_text("\n".join(render_env_lines(merged)) + "\n", encoding="utf-8")
    return True


def apply_install_dir_auth_env() -> None:
    """Load auth keys from the install folder when the data-dir .env omits them."""
    from shared.install_paths import frozen_bundle_dir, is_frozen

    if not is_frozen():
        return
    bundled = parse_env_file(frozen_bundle_dir() / ".env")
    for key in AUTH_ENV_KEYS:
        if os.environ.get(key, "").strip():
            continue
        val = bundled.get(key)
        if val:
            os.environ[key] = val


def bootstrap_server_env(data_root: Path) -> None:
    """Load data-dir .env, then fill missing auth keys from the install folder."""
    ensure_ssl_cert_bundle()
    try:
        from dotenv import load_dotenv

        load_dotenv(data_root / ".env")
    except ImportError:
        pass
    apply_install_dir_auth_env()


def ensure_ssl_cert_bundle() -> None:
    """PyInstaller onefile/onedir: make HTTPS (Supabase JWKS) use certifi roots."""
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
