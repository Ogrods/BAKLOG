"""Parity: shared/mirror_artifacts.py ↔ js/mirror-artifacts.js allowlist source."""

from __future__ import annotations

import re
from pathlib import Path

from shared.mirror_artifacts import (
    ALLOWED_ARTIFACT_RE_SOURCE,
    is_allowed_relative,
    is_denied_relative,
)

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "js" / "mirror-artifacts.js"


def _js_source_string() -> str:
    text = JS_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"ALLOWED_ARTIFACT_RE_SOURCE\s*=\s*\n?\s*['\"]([^'\"]+)['\"]",
        text,
    )
    assert m, "ALLOWED_ARTIFACT_RE_SOURCE not found in js/mirror-artifacts.js"
    # JS source uses double-escaped backslashes in a single-quoted string.
    return m.group(1).encode("utf-8").decode("unicode_escape")


def test_allowlist_source_matches_js() -> None:
    assert _js_source_string() == ALLOWED_ARTIFACT_RE_SOURCE
    landing = (ROOT / "landing" / "api" / "_mirror-helpers.js").read_text(encoding="utf-8")
    m = re.search(
        r'ALLOWED_ARTIFACT_RE_SOURCE\s*=\s*\n?\s*["\']([^"\']+)["\']',
        landing,
    )
    assert m, "ALLOWED_ARTIFACT_RE_SOURCE missing from landing helpers"
    assert m.group(1).encode("utf-8").decode("unicode_escape") == ALLOWED_ARTIFACT_RE_SOURCE


def test_allowlist_accepts_expected() -> None:
    assert is_allowed_relative("games_steam.json")
    assert is_allowed_relative("games_wishlist_steam.json")
    assert is_allowed_relative("itad_prices.json")
    assert is_allowed_relative("data/personal.json")


def test_allowlist_rejects_free_claims_and_credentials() -> None:
    assert not is_allowed_relative("free_claims.json")
    assert not is_allowed_relative("games_Steam.json")  # uppercase rejected
    assert not is_allowed_relative("cache/auth/secrets.bin")
    assert not is_allowed_relative("data/../../etc/passwd")
    assert is_denied_relative("../games_steam.json")
