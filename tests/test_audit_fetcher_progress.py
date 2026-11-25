"""scripts/audit_fetcher_progress.py coverage check."""
from __future__ import annotations

from scripts.audit_fetcher_progress import audit


def test_audit_fetcher_progress_runs():
    rows = audit()
    assert rows
    keys = {r["key"] for r in rows}
    assert "steam" in keys
    assert "gog" in keys
    # After vocal progress pass, loopish library keys should not be MISSING.
    missing = [r["key"] for r in rows if r["missing"]]
    assert "gog" not in missing
    assert "ea" not in missing
    assert "nintendo" not in missing
