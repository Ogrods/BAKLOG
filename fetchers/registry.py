"""Single source of truth for fetchers/manifest.json (server + audit tests)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "fetchers" / "manifest.json"

# Fetcher key -> connections provider id (for reconnect banners).
AUTH_PROVIDER_BY_KEY: dict[str, str] = {
    "steam": "steam",
    "gog": "gog",
    "psn": "psn",
    "epic": "epic",
    "amazon": "amazon",
    "xbox": "xbox",
    "battlenet": "battlenet",
    "ubisoft": "ubisoft",
    "nintendo": "nintendo",
    "itch": "itch",
    "humble": "humble",
    "ea": "ea",
    "wishlistSteam": "steam",
    "wishlistGog": "gog",
    "wishlistEpic": "epic_wishlist",
    "wishlistPsn": "psn",
    "wishlistUbisoft": "ubisoft",
    "wishlistXbox": "xbox_wishlist",
    "wishlistNintendo": "nintendo_wishlist",
    "wishlistHumble": "humble",
    "itad": "itad",
}

LIBRARY_JSON_BY_KEY: dict[str, str] = {
    "steam": "games_steam.json",
    "gog": "games_gog.json",
    "psn": "games_psn.json",
    "epic": "games_epic.json",
    "amazon": "games_amazon.json",
    "nintendo": "games_nintendo.json",
    "itch": "games_itch.json",
    "xbox": "games_xbox.json",
    "battlenet": "games_battlenet.json",
    "ubisoft": "games_ubisoft.json",
    "humble": "games_humble.json",
    "ea": "games_ea.json",
}

WISHLIST_JSON_BY_KEY: dict[str, str] = {
    "wishlistSteam": "games_wishlist.json",
    "wishlistGog": "games_wishlist_gog.json",
    "wishlistEpic": "games_wishlist_epic.json",
    "wishlistPsn": "games_wishlist_psn.json",
    "wishlistUbisoft": "games_wishlist_ubisoft.json",
    "wishlistXbox": "games_wishlist_xbox.json",
    "wishlistNintendo": "games_wishlist_nintendo.json",
    "wishlistHumble": "games_wishlist_humble.json",
}

WISHLIST_META_KEY_BY_FETCHER: dict[str, str] = {
    "wishlistSteam": "wishlist",
    "wishlistGog": "wishlistGog",
    "wishlistEpic": "wishlistEpic",
    "wishlistPsn": "wishlistPsn",
    "wishlistUbisoft": "wishlistUbisoft",
    "wishlistXbox": "wishlistXbox",
    "wishlistNintendo": "wishlistNintendo",
    "wishlistHumble": "wishlistHumble",
}

ENRICH_FETCHER_KEYS = frozenset({"hltb", "steamReviews", "steamCovers", "steamTags"})


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    p = path or MANIFEST_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    entries = raw.get("fetchers", [])
    if not isinstance(entries, list):
        raise ValueError("manifest fetchers must be a list")
    return raw


def manifest_entries(path: Path | None = None) -> list[dict[str, Any]]:
    return list(load_manifest(path).get("fetchers", []))


def entries_by_key(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in manifest_entries(path) if e.get("key")}


def validate_manifest(path: Path | None = None) -> list[str]:
    """Return human-readable validation errors (empty if ok)."""
    errors: list[str] = []
    entries = manifest_entries(path)
    keys = [e.get("key") for e in entries]
    if len(keys) != len(set(keys)):
        errors.append("duplicate manifest keys")
    for entry in entries:
        key = entry.get("key")
        script = entry.get("script")
        if not key or not script:
            errors.append(f"entry missing key or script: {entry!r}")
            continue
        if not (ROOT / script).is_file():
            errors.append(f"{key}: missing script {script}")
        group = entry.get("group", "library")
        meta = entry.get("metaKey", key)
        if group == "library" and key not in LIBRARY_JSON_BY_KEY:
            errors.append(f"{key}: library group but no LIBRARY_JSON_BY_KEY entry")
        if group == "wishlist" and key not in WISHLIST_JSON_BY_KEY:
            errors.append(f"{key}: wishlist group but no WISHLIST_JSON_BY_KEY entry")
        if group == "wishlist" and WISHLIST_META_KEY_BY_FETCHER.get(key) != meta:
            errors.append(f"{key}: metaKey {meta!r} != wishlist map {WISHLIST_META_KEY_BY_FETCHER.get(key)!r}")
        requires = entry.get("requires") or []
        if requires and group in ("library", "wishlist", "prices") and key not in AUTH_PROVIDER_BY_KEY:
            errors.append(f"{key}: has requires but no AUTH_PROVIDER_BY_KEY")
        refresh = entry.get("refreshArgs") or []
        if refresh:
            flags = _script_flags(script)
            for arg in refresh:
                if arg not in flags:
                    errors.append(f"{key}: refresh arg {arg} not in {script}")
    lib_manifest = {e["key"] for e in entries if e.get("group") == "library"}
    if lib_manifest != set(LIBRARY_JSON_BY_KEY):
        errors.append("library manifest keys != LIBRARY_JSON_BY_KEY")
    wl_manifest = {e["key"] for e in entries if e.get("group") == "wishlist"}
    if wl_manifest != set(WISHLIST_JSON_BY_KEY):
        errors.append("wishlist manifest keys != WISHLIST_JSON_BY_KEY")
    enrich_manifest = {e["key"] for e in entries if e.get("group") == "enrich"}
    if enrich_manifest != set(ENRICH_FETCHER_KEYS):
        errors.append("enrich manifest keys != ENRICH_FETCHER_KEYS")
    return errors


def _script_flags(script: str) -> set[str]:
    path = ROOT / script
    text = path.read_text(encoding="utf-8")
    flags: set[str] = set()
    for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)', text):
        flags.add(m.group(1))
    return flags


def export_js_registry(out_path: Path | None = None) -> None:
    """Write js/fetcher-registry.js for the browser bundle."""
    out = out_path or ROOT / "js" / "fetcher-registry.js"
    payload = {
        "libraryStoreJson": LIBRARY_JSON_BY_KEY,
        "wishlistFetcherJson": WISHLIST_JSON_BY_KEY,
        "wishlistFetcherMetaKey": WISHLIST_META_KEY_BY_FETCHER,
        "enrichFetcherKeys": sorted(ENRICH_FETCHER_KEYS),
        "authProviderByKey": AUTH_PROVIDER_BY_KEY,
    }
    lines = [
        "// Generated from fetchers/registry.py — keep in sync with manifest maps.",
        "// Regenerate: python -c \"from fetchers.registry import export_js_registry; export_js_registry()\"",
        "",
        f"export const LIBRARY_STORE_JSON = {json.dumps(payload['libraryStoreJson'], indent=2)};",
        "",
        f"export const WISHLIST_FETCHER_JSON = {json.dumps(payload['wishlistFetcherJson'], indent=2)};",
        "",
        f"export const WISHLIST_FETCHER_META_KEY = {json.dumps(payload['wishlistFetcherMetaKey'], indent=2)};",
        "",
        f"export const ENRICH_FETCHER_KEYS = new Set({json.dumps(payload['enrichFetcherKeys'])});",
        "",
        f"export const FETCHER_AUTH_PROVIDER = {json.dumps(payload['authProviderByKey'], indent=2)};",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    errs = validate_manifest()
    if errs:
        raise SystemExit("\n".join(errs))
    export_js_registry()
    print("fetcher-registry.js updated")
