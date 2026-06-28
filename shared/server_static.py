import os
import re
from pathlib import Path
from urllib.parse import unquote

from shared.profile_paths import PROFILE_CACHE_JSON_FILES

LIBRARY_JSON_RE = re.compile("^/games_[a-z0-9_]+\\.json$", re.I)


def normalize_static_path(path_only):
    clean = path_only.split("?", 1)[0]
    if not clean.startswith("/"):
        clean = "/" + clean.lstrip("/")
    try:
        decoded = unquote(clean, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        decoded = clean
    segments = []
    for seg in decoded.split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            if segments:
                segments.pop()
            continue
        segments.append(seg.casefold())
    return "/" + "/".join(segments) if segments else "/"


def static_class(path_only, *, admin_enabled=None):
    clean = normalize_static_path(path_only)
    parts = [p for p in clean.split("/") if p]
    if parts and parts[-1] == "tracker.html":
        return "deny"
    if parts and parts[0] == "admin":
        if admin_enabled is None:
            admin_enabled = os.environ.get("BAKLOG_ADMIN") == "1"
        if not admin_enabled:
            return "deny"
        return "public"
    if any(p.startswith(".") for p in parts):
        return "deny"
    if parts and parts[0] == "profiles":
        return "deny"
    if parts and parts[0] == "data":
        return "deny"
    if len(parts) >= 2 and parts[0] == "cache":
        if parts[1] == "auth":
            return "deny"
        if parts[1] in PROFILE_CACHE_JSON_FILES:
            return "data"
        return "deny"
    if LIBRARY_JSON_RE.match(clean) or clean.lower() in ("/itad_prices.json", "/free_claims.json", "/sponsors.json"):
        return "data"
    return "public"


def resolved_static_path_allowed(resolved):
    try:
        real = Path(resolved).resolve()
    except OSError:
        return False
    if ".profile_static_blocked" in real.parts:
        return False
    from shared.install_paths import bundle_root
    from shared.profile_paths import ROOT as profile_data_root

    rel_posix = None
    for root in (profile_data_root.resolve(), bundle_root().resolve()):
        try:
            rel_posix = real.relative_to(root).as_posix()
            break
        except ValueError:
            continue
    if rel_posix is None:
        return False
    parts = [p.casefold() for p in rel_posix.split("/") if p and p != "."]
    if not parts:
        return True
    if parts[-1] in (".env", "tracker.html"):
        return False
    if any(p.startswith(".") for p in parts):
        return False
    if "data" in parts:
        return False
    for i in range(len(parts) - 1):
        if parts[i] == "cache" and parts[i + 1] == "auth":
            return False
    return True
