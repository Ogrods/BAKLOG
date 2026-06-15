"""Fetcher scripts must accept manifest/dashboard CLI flags."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_help(script: str) -> subprocess.CompletedProcess[str]:
    rel = script if "/" in script else f"fetchers/{script}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, rel, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


_NO_DUPLICATE_ALLOW_DRIFT = (
    "fetchers/fetch_ea.py",
    "fetchers/fetch_itch.py",
    "fetchers/fetch_gog.py",
    "fetchers/fetch_amazon.py",
)


def test_fetch_ea_help_exits_zero() -> None:
    """Duplicate --allow-drift registration crashes argparse before --help."""
    proc = _run_help("fetchers.fetch_ea.py")
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, combined
    assert "conflicting option" not in combined.lower()
    assert "--allow-drift" in combined


def test_fetch_scripts_do_not_duplicate_allow_drift_in_source() -> None:
    """Manual --allow-drift plus add_allow_empty_arg() causes argparse conflict."""
    for script in _NO_DUPLICATE_ALLOW_DRIFT:
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "add_allow_empty_arg" in text, f"{script} should use add_allow_empty_arg"
        manual = text.count('parser.add_argument("--allow-drift"')
        assert manual == 0, (
            f"{script} registers --allow-drift manually; use add_allow_empty_arg only"
        )


def test_fetch_nintendo_help_lists_rebuild_flag() -> None:
    proc = _run_help("fetchers.fetch_nintendo.py")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "--rebuild" in (proc.stdout or "")


def test_fetch_humble_accepts_skip_hltb_flag() -> None:
    """Manifest passes --skip-hltb; script must advertise it in --help."""
    proc = _run_help("fetchers.fetch_humble.py")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "--skip-hltb" in (proc.stdout or "")
