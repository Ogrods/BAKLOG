"""Child-mode entry: BAKLOG.exe --run-fetcher <key> [args...]"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from fetchers.registry import MANIFEST_PATH


def _module_for_script(script: str) -> str:
    return Path(script).stem


def run_fetcher(key: str, args: list[str]) -> int:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = raw.get("fetchers") or []
    entry = next((e for e in entries if e.get("key") == key), None)
    if not entry:
        print(f"[fetcher] unknown key: {key!r}", file=sys.stderr)
        return 2
    script = entry.get("script")
    if not script:
        print(f"[fetcher] manifest entry {key!r} has no script", file=sys.stderr)
        return 2
    module_name = _module_for_script(str(script))
    mod = importlib.import_module(module_name)
    main = getattr(mod, "main", None)
    if not callable(main):
        print(f"[fetcher] {module_name} has no main()", file=sys.stderr)
        return 2
    sys.argv = [str(script), *args]
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    if code is None:
        return 0
    return int(code)
