"""Repo size guardrails — keep monolith files from growing without review."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ratchet down after intentional splits (see scripts/check-module-size.mjs).
SERVER_PY_MAX_LINES = 4400


def test_server_py_line_budget():
    server = ROOT / "server.py"
    lines = server.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= SERVER_PY_MAX_LINES, (
        f"server.py has {len(lines)} lines (budget {SERVER_PY_MAX_LINES}). "
        "Split routes/helpers into shared/ or ratchet the cap after review."
    )
