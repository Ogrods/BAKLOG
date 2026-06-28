import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUTH_EXIT_SCRIPTS = [
    "fetchers/fetch_gog.py",
    "fetchers/fetch_gog_wishlist.py",
    "fetchers/fetch_psn.py",
    "fetchers/fetch_psn_wishlist.py",
    "fetchers/fetch_epic.py",
    "fetchers/fetch_xbox.py",
    "fetchers/fetch_battlenet.py",
    "fetchers/fetch_nintendo.py",
    "fetchers/fetch_ubisoft.py",
    "fetchers/fetch_itch.py",
    "fetchers/fetch_ea.py",
]
SESSION_AUTH_WISHLIST_SCRIPTS = [
    "fetchers/fetch_epic_wishlist.py",
    "fetchers/fetch_xbox_wishlist.py",
    "fetchers/fetch_ubisoft_wishlist.py",
    "fetchers/fetch_nintendo_wishlist.py",
]
AUTH_EXIT_SCRIPTS_GENERIC = [
    "fetchers/fetch_amazon.py",
    "fetchers/fetch_humble.py",
    "fetchers/fetch_humble_wishlist.py",
    "fetchers/fetch_games.py",
    "fetchers/fetch_wishlist.py",
]


def _auth_error_finish_exit_codes(text):
    codes = []
    for m in re.finditer("^(\\s*)except\\s+\\w*AuthError\\b[^:]*:", text, re.MULTILINE):
        body_prefix = m.group(1) + "    "
        body_lines = []
        for line in text[m.end() :].splitlines():
            if not line.strip():
                if body_lines:
                    body_lines.append(line)
                continue
            if line.startswith(body_prefix):
                body_lines.append(line)
                continue
            break
        chunk = "\n".join(body_lines)
        if "return stats.finish" not in chunk:
            continue
        finish = re.search("return\\s+stats\\.finish\\([^)]*exit_code=(\\w+)", chunk)
        if finish:
            codes.append(finish.group(1))
    return codes


@pytest.mark.parametrize("script", AUTH_EXIT_SCRIPTS)
def test_auth_error_branches_use_exit_code_4(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "EXIT_CODE_AUTH" in text, f"{script} must import EXIT_CODE_AUTH"
    assert "mark_invalid" in text, f"{script} must call mark_invalid on auth failure"
    blocks = _auth_error_finish_exit_codes(text)
    assert blocks, f"{script} has no AuthError -> stats.finish exit path"
    assert all((code == "EXIT_CODE_AUTH" for code in blocks)), (
        f"{script} AuthError branches must use exit_code=EXIT_CODE_AUTH, got {blocks}"
    )


@pytest.mark.parametrize("script", SESSION_AUTH_WISHLIST_SCRIPTS)
def test_wishlist_session_auth_uses_exit_code_4(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "EXIT_CODE_AUTH" in text
    assert "mark_invalid" in text
    assert "exit_code=EXIT_CODE_AUTH" in text


@pytest.mark.parametrize("script", AUTH_EXIT_SCRIPTS_GENERIC)
def test_auth_failure_paths_use_exit_code_4(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "EXIT_CODE_AUTH" in text, f"{script} must import EXIT_CODE_AUTH"
    assert "mark_invalid" in text, f"{script} must call mark_invalid on auth failure"
    assert "exit_code=EXIT_CODE_AUTH" in text, f"{script} must finish with exit_code=EXIT_CODE_AUTH on auth failure"
