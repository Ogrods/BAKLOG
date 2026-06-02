"""Unified enricher entry: ``python -m enrichers <command>``."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMMANDS: dict[str, list[str]] = {
    "hltb": [sys.executable, str(ROOT / "enrich_hltb.py")],
    "steam-reviews": [sys.executable, str(ROOT / "enrich_steam_reviews.py")],
    "steam-tags": [sys.executable, str(ROOT / "enrich_steam_tags.py")],
    "cross-store-images": [sys.executable, str(ROOT / "enrich_cross_store_images.py")],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run enrichment scripts (HLTB, Steam reviews, cross-store images).",
    )
    parser.add_argument(
        "command",
        choices=sorted(COMMANDS),
        help="Which enricher to run",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to the underlying script",
    )
    ns = parser.parse_args(argv)
    cmd = COMMANDS[ns.command] + ns.args
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
