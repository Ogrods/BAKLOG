"""Cross-check manifest.json vs fetch scripts and UI wiring."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import server
from fetchers.registry import (
    AUTH_PROVIDER_BY_KEY,
    ENRICH_FETCHER_KEYS,
    LIBRARY_JSON_BY_KEY,
    MANIFEST_PATH,
    WISHLIST_JSON_BY_KEY,
    WISHLIST_META_KEY_BY_FETCHER,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ENTRIES = MANIFEST["fetchers"]

# Mirrors js/fetcher-registry.js (generated from fetchers/registry.py)
LIBRARY_STORE_JSON = LIBRARY_JSON_BY_KEY
WISHLIST_FETCHER_JSON = WISHLIST_JSON_BY_KEY
ENRICH_KEYS = set(ENRICH_FETCHER_KEYS)


def _script_flags(script: str) -> set[str]:
    path = ROOT / script
    text = path.read_text(encoding="utf-8")
    flags: set[str] = set()
    for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)', text):
        flags.add(m.group(1))
    if "add_hltb_args" in text:
        base = (ROOT / "fetchers/_base.py").read_text(encoding="utf-8")
        for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)', base):
            flags.add(m.group(1))
    return flags


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["key"] for e in ENTRIES])
def test_manifest_script_exists(entry: dict) -> None:
    script = ROOT / entry["script"]
    assert script.is_file(), f"missing script {entry['script']}"


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["key"] for e in ENTRIES])
def test_manifest_args_supported_by_script(entry: dict) -> None:
    args = entry.get("args") or []
    if not args:
        return
    flags = _script_flags(entry["script"])
    for arg in args:
        assert arg in flags, f"{entry['key']}: {arg} not in {entry['script']}"


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["key"] for e in ENTRIES])
def test_refresh_args_supported_by_script(entry: dict) -> None:
    refresh = entry.get("refreshArgs") or []
    if not refresh:
        return
    flags = _script_flags(entry["script"])
    for arg in refresh:
        assert arg in flags, f"{entry['key']}: {arg} not in {entry['script']}"


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["key"] for e in ENTRIES])
def test_reload_mapping(entry: dict) -> None:
    key = entry["key"]
    if key in ENRICH_KEYS or key == "itad":
        return
    assert key in LIBRARY_STORE_JSON or key in WISHLIST_FETCHER_JSON, (
        f"{key} has no reloadAfterFetcher mapping in app.js"
    )


def test_manifest_keys_unique() -> None:
    keys = [e["key"] for e in ENTRIES]
    assert len(keys) == len(set(keys))


def test_all_library_manifest_keys_in_app_js() -> None:
    lib_keys = {e["key"] for e in ENTRIES if e.get("group") == "library"}
    assert lib_keys == set(LIBRARY_STORE_JSON.keys())


def test_wishlist_manifest_keys_in_app_js() -> None:
    wl_keys = {e["key"] for e in ENTRIES if e.get("group") == "wishlist"}
    assert wl_keys == set(WISHLIST_FETCHER_JSON.keys())


# Documented empty-guard policy (refuse_empty or manual exit 2 before write)
REFUSE_EMPTY_SCRIPTS = {
    "fetch_games.py",
    "fetch_gog.py",
    "fetch_epic.py",
    "fetch_psn.py",
    "fetch_xbox.py",
    "fetch_gog_wishlist.py",
    "fetch_epic_wishlist.py",
    "fetch_psn_wishlist.py",
    "fetch_ubisoft_wishlist.py",
    "fetch_xbox_wishlist.py",
    "fetch_nintendo_wishlist.py",
    "fetch_humble.py",
    "fetch_humble_wishlist.py",
    "fetch_wishlist.py",
    "fetch_itad.py",
    "fetch_itch.py",
    "fetch_battlenet.py",
    "fetch_nintendo.py",
    "fetch_ubisoft.py",
    "fetch_ea.py",
}
MANUAL_EMPTY_EXIT_SCRIPTS = {
    "fetch_amazon.py",
}
DRIFT_GUARD_BY_SCRIPT: dict[str, str] = {
    "fetch_amazon.py": "refuse_amazon_source_drift",
    "fetch_gog.py": "refuse_gog_source_drift",
    "fetch_itch.py": "refuse_itch_source_drift",
}
NO_EMPTY_GUARD_SCRIPTS = {
    "enrich_hltb.py",
    "enrich_steam_reviews.py",
    "enrich_cross_store_images.py",
    "enrich_steam_tags.py",
}


@pytest.mark.parametrize(
    "script",
    sorted(REFUSE_EMPTY_SCRIPTS),
)
def test_refuse_empty_helper(script: str) -> None:
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "refuse_empty_result" in text
    assert "add_allow_empty_arg" in text


@pytest.mark.parametrize(
    "script",
    sorted(MANUAL_EMPTY_EXIT_SCRIPTS),
)
def test_manual_empty_guard(script: str) -> None:
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "exit_code=2" in text
    assert DRIFT_GUARD_BY_SCRIPT.get(script, "refuse_drift_result") in text


@pytest.mark.parametrize(
    "script",
    sorted(NO_EMPTY_GUARD_SCRIPTS),
)
def test_documented_no_standard_empty_guard(script: str) -> None:
    """Enrichers mutate in place; Steam/PSN trust non-zero library from API."""
    assert script in NO_EMPTY_GUARD_SCRIPTS


def test_registry_validate_manifest() -> None:
    assert validate_manifest() == []


def test_server_fetchers_match_manifest() -> None:
    assert set(server.FETCHERS.keys()) == {e["key"] for e in ENTRIES}


def _parse_js_const_object(name: str, text: str) -> dict:
    pattern = rf"export const {name} = (\{{[\s\S]*?\}});\n"
    match = re.search(pattern, text)
    assert match, f"missing export const {name} in fetcher-registry.js"
    return json.loads(match.group(1))


def _parse_js_const_set(name: str, text: str) -> set[str]:
    pattern = rf"export const {name} = new Set\((\[.*?\])\);"
    match = re.search(pattern, text)
    assert match, f"missing export const {name} in fetcher-registry.js"
    return set(json.loads(match.group(1)))


def test_committed_fetcher_registry_js_matches_python() -> None:
    """Committed js/fetcher-registry.js must match fetchers/registry.py maps."""
    js_text = (ROOT / "js" / "fetcher-registry.js").read_text(encoding="utf-8")
    assert _parse_js_const_object("LIBRARY_STORE_JSON", js_text) == LIBRARY_JSON_BY_KEY
    assert _parse_js_const_object("WISHLIST_FETCHER_JSON", js_text) == WISHLIST_JSON_BY_KEY
    assert _parse_js_const_object("WISHLIST_FETCHER_META_KEY", js_text) == WISHLIST_META_KEY_BY_FETCHER
    assert _parse_js_const_set("ENRICH_FETCHER_KEYS", js_text) == set(ENRICH_FETCHER_KEYS)
    assert _parse_js_const_object("FETCHER_AUTH_PROVIDER", js_text) == AUTH_PROVIDER_BY_KEY
