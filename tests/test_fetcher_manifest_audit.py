"""Cross-check manifest.json vs fetch scripts and UI wiring."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "fetchers" / "manifest.json").read_text(encoding="utf-8"))
ENTRIES = MANIFEST["fetchers"]

# Mirrors js/app.js
LIBRARY_STORE_JSON = {
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
}
WISHLIST_FETCHER_JSON = {
    "wishlistSteam": "games_wishlist.json",
    "wishlistGog": "games_wishlist_gog.json",
    "wishlistEpic": "games_wishlist_epic.json",
}
ENRICH_KEYS = {"hltb", "steamReviews", "steamCovers"}


def _script_flags(script: str) -> set[str]:
    path = ROOT / script
    text = path.read_text(encoding="utf-8")
    flags: set[str] = set()
    for m in re.finditer(r'add_argument\(\s*["\'](--[\w-]+)', text):
        flags.add(m.group(1))
    return flags


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["key"] for e in ENTRIES])
def test_manifest_script_exists(entry: dict) -> None:
    script = ROOT / entry["script"]
    assert script.is_file(), f"missing script {entry['script']}"


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
    "fetch_wishlist.py",
    "fetch_itad.py",
}
MANUAL_EMPTY_EXIT_SCRIPTS = {
    "fetch_amazon.py",
    "fetch_battlenet.py",
    "fetch_nintendo.py",
    "fetch_itch.py",
    "fetch_ubisoft.py",
}
NO_EMPTY_GUARD_SCRIPTS = {
    "enrich_hltb.py",
    "enrich_steam_reviews.py",
    "enrich_cross_store_images.py",
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


@pytest.mark.parametrize(
    "script",
    sorted(NO_EMPTY_GUARD_SCRIPTS),
)
def test_documented_no_standard_empty_guard(script: str) -> None:
    """Enrichers mutate in place; Steam/PSN trust non-zero library from API."""
    assert script in NO_EMPTY_GUARD_SCRIPTS
