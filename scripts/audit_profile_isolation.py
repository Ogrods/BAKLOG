#!/usr/bin/env python3
"""Backward-compatible entry point — see scripts/audit_security.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_security import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
