"""Auth-failure fetchers must exit with EXIT_CODE_AUTH (4) and call mark_invalid."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Fetch scripts with dedicated *AuthError handlers (or session-expired wishlist paths).
AUTH_EXIT_SCRIPTS = [
    "fetch_gog.py",
    "fetch_gog_wishlist.py",
    "fetch_psn.py",
    "fetch_psn_wishlist.py",
    "fetch_epic.py",
    "fetch_epic_wishlist.py",
    "fetch_xbox.py",
    "fetch_battlenet.py",
    "fetch_nintendo.py",
    "fetch_ubisoft.py",
    "fetch_itch.py",
    "fetch_ea.py",
]

SESSION_AUTH_WISHLIST_SCRIPTS = [
    "fetch_xbox_wishlist.py",
    "fetch_ubisoft_wishlist.py",
]


@pytest.mark.parametrize("script", AUTH_EXIT_SCRIPTS)
def test_auth_error_branches_use_exit_code_4(script: str) -> None:
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "EXIT_CODE_AUTH" in text, f"{script} must import EXIT_CODE_AUTH"
    assert "mark_invalid" in text, f"{script} must call mark_invalid on auth failure"
    # Every AuthError except block should finish with exit_code=EXIT_CODE_AUTH.
    blocks = re.findall(
        r"except\s+\w*AuthError[^:]*:.*?return\s+stats\.finish\([^)]*exit_code=(\w+)",
        text,
        flags=re.DOTALL,
    )
    assert blocks, f"{script} has no AuthError -> stats.finish exit path"
    assert all(code == "EXIT_CODE_AUTH" for code in blocks), (
        f"{script} AuthError branches must use exit_code=EXIT_CODE_AUTH, got {blocks}"
    )


@pytest.mark.parametrize("script", SESSION_AUTH_WISHLIST_SCRIPTS)
def test_wishlist_session_auth_uses_exit_code_4(script: str) -> None:
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "EXIT_CODE_AUTH" in text
    assert "mark_invalid" in text
    assert "exit_code=EXIT_CODE_AUTH" in text
