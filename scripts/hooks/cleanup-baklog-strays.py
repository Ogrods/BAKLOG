#!/usr/bin/env python3
"""Cursor stop hook: dedupe stray BAKLOG dev servers when an agent turn ends.

Keeps the one server currently listening on the dev port and force-stops any
other ``server.py`` / ``tray_app.py`` leftovers (plus a stale pid file), so
abandoned agent terminals don't pile up. Never kills the live server a session
is actively using. Best-effort: any failure exits 0 so the agent is never
blocked.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = ROOT / ".venv" / "bin" / "python"
    try:
        _res = subprocess.run(
            [str(python), str(ROOT / "scripts" / "stop_baklog.py"), "--dedupe"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        pass

    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
