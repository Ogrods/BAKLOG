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


def bundled_auth_values(install_dir: Path) -> dict[str, str]:
    """Auth keys shipped beside the frozen exe (source of truth for beta builds)."""
    bundled = parse_env_file(install_dir / ".env")
    if not bundled.get("BAKLOG_SUPABASE_URL") or not bundled.get("BAKLOG_SUPABASE_ANON_KEY"):
        return {}
    return {k: bundled[k] for k in AUTH_ENV_KEYS if bundled.get(k)}


def sync_bundled_auth_env_to_data_dir(install_dir: Path, data_dir: Path) -> bool:
    """Align data_dir/.env auth keys with the install-dir bundle.

    Fills missing keys and overwrites stale values left by older installers or
    partial migrations (upgrade path where BAKLOG-Data kept a wrong .env).
    """
    bundled = bundled_auth_values(install_dir)
    if not bundled:
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / ".env"
    merged = parse_env_file(dest)
    changed = False
    for key, val in bundled.items():
        if merged.get(key) != val:
            merged[key] = val
            changed = True
    if not changed and dest.is_file():
        return False
    if not merged:
        return False
    dest.write_text("\n".join(render_env_lines(merged)) + "\n", encoding="utf-8")
    return True


def apply_install_dir_auth_env() -> None:
    """Load auth keys from the install folder.

    Frozen builds: install-dir bundle always wins so a stale data-dir .env
    cannot block JWT verification after an in-place upgrade.
    """
    from shared.install_paths import frozen_bundle_dir, is_frozen

    if not is_frozen():
        return
    bundled = bundled_auth_values(frozen_bundle_dir())
    if not bundled:
        return
    for key, val in bundled.items():
        os.environ[key] = val


def bootstrap_server_env(data_root: Path) -> None:
    """Load data-dir .env, then apply install-dir auth (frozen wins on conflicts)."""
    ensure_ssl_cert_bundle()
    try:
        from dotenv import load_dotenv

        load_dotenv(data_root / ".env")
    except ImportError:
        pass
    apply_install_dir_auth_env()
    warmup_auth_verification()


def ensure_ssl_cert_bundle() -> None:
    """PyInstaller onefile/onedir: make HTTPS (Supabase JWKS) use certifi roots."""
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


def warmup_auth_verification() -> None:
    """Prime JWKS fetch at boot so the first sign-in probe is not a cold HTTPS miss."""
    try:
        from shared.supabase_auth import warmup_jwks_client

        warmup_jwks_client()
    except Exception:
        pass
