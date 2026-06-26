"""PROFILE_CACHE_JSON_FILES must stay aligned across Python server and JS client."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import server
from shared.profile_paths import PROFILE_CACHE_JSON_FILES

ROOT = Path(__file__).resolve().parents[1]
API_CLIENT = (ROOT / "js" / "api-client.js").read_text(encoding="utf-8")


def _cache_names_from_js() -> set[str]:
    m = re.search(
        r"const _CACHE_META_RE = /\^\\/cache\\/\(([^)]+)\)\\\.json",
        API_CLIENT,
    )
    assert m, "_CACHE_META_RE not found in js/api-client.js"
    return {name.strip() for name in m.group(1).split("|")}


def test_profile_cache_files_match_api_client_regex() -> None:
    py_names = {name.replace(".json", "") for name in PROFILE_CACHE_JSON_FILES}
    js_names = _cache_names_from_js()
    assert py_names == js_names


def test_server_empty_cache_stubs_cover_all_profile_cache_files() -> None:
    stub_names = {name.replace(".json", "") for name in server._EMPTY_CACHE_META_JSON}
    py_names = {name.replace(".json", "") for name in PROFILE_CACHE_JSON_FILES}
    assert stub_names == py_names
