"""Fetcher scripts must accept manifest/dashboard CLI flags."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_fetch_ea_help_exits_zero() -> None:
    """Duplicate --allow-drift registration crashes argparse before --help."""
    proc = subprocess.run(
        [sys.executable, "fetch_ea.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_fetch_humble_accepts_skip_hltb_flag() -> None:
    """Manifest passes --skip-hltb; script must not reject it at parse time."""
    proc = subprocess.run(
        [sys.executable, "fetch_humble.py", "--skip-hltb", "--allow-empty"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = (proc.stderr or "") + (proc.stdout or "")
    assert "unrecognized arguments" not in combined
    assert proc.returncode != 2
