import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
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
