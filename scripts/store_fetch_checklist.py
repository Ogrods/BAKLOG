from __future__ import annotations
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'fetchers' / 'manifest.json'
BASE = 'http://127.0.0.1:8765'

def load_fetchers() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    return list(data.get('fetchers') or [])

def ping_server() -> bool:
    try:
        with urllib.request.urlopen(f'{BASE}/api/runs', timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ping', action='store_true', help='Verify server responds on :8765')
    args = parser.parse_args()
    if args.ping:
        ok = ping_server()
        print(f"Server {('up' if ok else 'down')} at {BASE}")
        if not ok:
            return 1
    fetchers = load_fetchers()
    library = [f for f in fetchers if f.get('group') == 'library']
    other = [f for f in fetchers if f.get('group') != 'library']
    print('Pre-go-live per-store fetch checklist')
    print('=' * 40)
    for f in library:
        key = f.get('key', '?')
        label = f.get('label', key)
        script = f.get('script', '')
        print(f'  [ ] {key:16} {label:14}  ({script})')
    if other:
        print('\nEnrichment / other:')
        for f in other:
            key = f.get('key', '?')
            label = f.get('label', key)
            print(f'  [ ] {key:16} {label}')
    print('\nRun each fetcher from the dashboard Fetcher health row or via python fetch_*.py')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())