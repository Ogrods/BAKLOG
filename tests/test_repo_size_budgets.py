from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_PY_MAX_LINES = 3000
GIT_TREE_PY_MAX_LINES = 720


def test_server_py_line_budget():
    server = ROOT / "server.py"
    lines = server.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= SERVER_PY_MAX_LINES, (
        f"server.py has {len(lines)} lines (budget {SERVER_PY_MAX_LINES}). Split routes/helpers into shared/ or ratchet the cap after review."
    )


def test_git_tree_py_line_budget():
    script = ROOT / "scripts" / "git_tree.py"
    lines = script.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= GIT_TREE_PY_MAX_LINES, (
        f"scripts/git_tree.py has {len(lines)} lines (budget {GIT_TREE_PY_MAX_LINES}). Split embedded assets or ratchet the cap after review."
    )
