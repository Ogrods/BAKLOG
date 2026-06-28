from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
_LEGACY_ALIASES: dict[str, str] = {'steam-reviews': 'steamReviews', 'steam-tags': 'steamTags', 'cross-store-images': 'steamCovers'}

def _commands_from_manifest() -> dict[str, list[str]]:
    from fetchers.registry import manifest_entries
    out: dict[str, list[str]] = {}
    for entry in manifest_entries():
        if entry.get('group') != 'enrich':
            continue
        key = entry['key']
        script = entry.get('script')
        if not key or not script:
            continue
        out[key] = [sys.executable, str(ROOT / script)]
    for legacy, key in _LEGACY_ALIASES.items():
        if key in out:
            out[legacy] = out[key]
    return out
COMMANDS = _commands_from_manifest()

def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description='Run enrichment scripts (HLTB, Steam reviews, cross-store images).')
    parser.add_argument('command', choices=sorted(COMMANDS), help='Which enricher to run')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='Arguments passed through to the underlying script')
    ns = parser.parse_args(argv)
    cmd = COMMANDS[ns.command] + ns.args
    env = {**dict(__import__('os').environ), 'PYTHONPATH': str(ROOT)}
    return subprocess.call(cmd, env=env)
if __name__ == '__main__':
    raise SystemExit(main())