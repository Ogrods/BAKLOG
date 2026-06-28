from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
EXIT_LABELS = {0: 'ok', 1: 'error', 2: 'empty_refused', 3: 'drift_refused', 4: 'auth'}
LIVE_WITHOUT_PROVIDER = frozenset({'claims', 'hltb', 'steamCovers', 'steamReviews', 'steamTags', 'protondb'})
DEFAULT_TIMEOUTS: dict[str, int] = {'hltb': 90, 'steamCovers': 90, 'steamReviews': 90, 'steamTags': 90, 'protondb': 90, 'claims': 120, 'itad': 120}
DEFAULT_TIMEOUT = 180

def _load_manifest_keys() -> list[dict]:
    from fetchers.registry import load_manifest
    raw = load_manifest()
    return [e for e in raw.get('fetchers') or [] if e.get('key')]

def _connected_fetcher_keys(data_dir: Path, profile: str | None) -> set[str]:
    os.environ['BAKLOG_DATA_DIR'] = str(data_dir.resolve())
    if profile:
        os.environ['BAKLOG_PROFILE'] = profile
    from auth.manager import get_status
    keys: set[str] = set(LIVE_WITHOUT_PROVIDER)
    for row in get_status():
        if row.get('status') not in ('connected', 'unverified'):
            continue
        for fk in row.get('fetcher_keys') or []:
            keys.add(str(fk))
    return keys

def _run(exe: Path, key: str, extra: list[str], env: dict[str, str], timeout: int) -> dict:
    cmd = [str(exe), '--run-fetcher', key, *extra]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=str(exe.parent))
        elapsed = time.monotonic() - started
        out = (proc.stdout or '') + (proc.stderr or '')
        tail = '\n'.join(out.strip().splitlines()[-8:])
        return {'key': key, 'exit': proc.returncode, 'exit_label': EXIT_LABELS.get(proc.returncode, f'code_{proc.returncode}'), 'seconds': round(elapsed, 1), 'tail': tail}
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        out = (exc.stdout or '') + (exc.stderr or '') if exc.stdout or exc.stderr else ''
        if isinstance(out, bytes):
            out = out.decode('utf-8', errors='replace')
        tail = '\n'.join(out.strip().splitlines()[-8:])
        return {'key': key, 'exit': None, 'exit_label': 'timeout', 'seconds': round(elapsed, 1), 'tail': tail}

def _dispatch_ok(row: dict) -> bool:
    return row['exit'] == 0

def _live_ok(row: dict) -> bool:
    return row['exit'] in (0, 2, 3)

def main() -> int:
    ap = argparse.ArgumentParser(description='Frozen fetcher fleet smoke test')
    ap.add_argument('--exe', type=Path, default=_REPO / 'release' / 'BAKLOG' / 'BAKLOG.exe')
    ap.add_argument('--data-dir', type=Path, default=_REPO)
    ap.add_argument('--profile', default=os.environ.get('BAKLOG_PROFILE', '').strip() or None)
    ap.add_argument('--dispatch-only', action='store_true', help='Only run --help dispatch checks')
    ap.add_argument('--json-out', type=Path, default=None)
    args = ap.parse_args()
    exe = args.exe.resolve()
    if not exe.is_file():
        print(f'BAKLOG.exe not found: {exe}', file=sys.stderr)
        return 2
    data_dir = args.data_dir.resolve()
    env = os.environ.copy()
    env['BAKLOG_DATA_DIR'] = str(data_dir)
    if args.profile:
        env['BAKLOG_PROFILE'] = args.profile
    entries = _load_manifest_keys()
    keys = [e['key'] for e in entries]
    print(f'Frozen smoke: {exe.name} @ {exe.parent}')
    print(f'Data dir: {data_dir}')
    if args.profile:
        print(f'Profile override: {args.profile}')
    print(f'Fetchers in manifest: {len(keys)}')
    dispatch_rows: list[dict] = []
    for entry in entries:
        key = entry['key']
        row = _run(exe, key, ['--help'], env, timeout=45)
        dispatch_rows.append(row)
        mark = 'PASS' if _dispatch_ok(row) else 'FAIL'
        print(f"  dispatch {key:18} {mark} ({row['exit_label']}, {row['seconds']}s)")
    live_rows: list[dict] = []
    skipped: list[dict] = []
    if not args.dispatch_only:
        live_keys = _connected_fetcher_keys(data_dir, args.profile)
        print(f'Live candidates (connected + enrich): {len(live_keys)}')
        for entry in entries:
            key = entry['key']
            if key not in live_keys:
                skipped.append({'key': key, 'reason': 'not_connected'})
                continue
            extra = list(entry.get('args') or ['--skip-hltb'])
            timeout = DEFAULT_TIMEOUTS.get(key, DEFAULT_TIMEOUT)
            row = _run(exe, key, extra, env, timeout=timeout)
            live_rows.append(row)
            mark = 'PASS' if _live_ok(row) else 'FAIL'
            print(f"  live     {key:18} {mark} ({row['exit_label']}, {row['seconds']}s)")
    dispatch_fail = [r for r in dispatch_rows if not _dispatch_ok(r)]
    live_fail = [r for r in live_rows if not _live_ok(r)]
    report = {'exe': str(exe), 'data_dir': str(data_dir), 'profile': args.profile, 'dispatch': dispatch_rows, 'live': live_rows, 'live_skipped': skipped, 'summary': {'dispatch_pass': len(dispatch_rows) - len(dispatch_fail), 'dispatch_fail': len(dispatch_fail), 'live_pass': len(live_rows) - len(live_fail), 'live_fail': len(live_fail), 'live_skipped': len(skipped)}}
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Wrote {args.json_out}')
    print(f"\nSummary: dispatch {report['summary']['dispatch_pass']}/{len(dispatch_rows)}, live {report['summary']['live_pass']}/{len(live_rows)} ({report['summary']['live_skipped']} skipped not connected)")
    if dispatch_fail or live_fail:
        print('\nFailures:')
        for row in dispatch_fail + live_fail:
            print(f"  {row['key']}: {row['exit_label']}")
            if row.get('tail'):
                print(f"    tail: {row['tail'][:240]}")
        return 1
    return 0
if __name__ == '__main__':
    raise SystemExit(main())