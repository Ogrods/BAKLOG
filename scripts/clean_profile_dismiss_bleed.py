from __future__ import annotations
import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ROOT / 'profiles'
BLEED_KEYS = ('__dismissedClaims', '__dismissedClaimKeys', '__purgedClaimKeys')

def _load_personal(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(doc.get('personal'), dict):
        return doc
    return {'personal': doc if isinstance(doc, dict) else {}}

def _backup(path: Path) -> Path:
    backup_dir = path.parent / 'personal_backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')
    dest = backup_dir / f'personal-{stamp}.json'
    shutil.copy2(path, dest)
    return dest

def _bleed_ids(default_maps: dict[str, dict[str, Any]], profile_maps: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    removed: dict[str, list[str]] = {}
    for key in BLEED_KEYS:
        d_map = default_maps.get(key) or {}
        p_map = profile_maps.get(key) or {}
        bleed = [cid for cid in p_map if cid in d_map and p_map[cid] == d_map[cid]]
        if bleed:
            removed[key] = bleed
    return removed

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    parser.add_argument('--reference', default='default', help='Reference profile id to treat as source of inherited entries (default: default)')
    parser.add_argument('--strip-peer', nargs=2, metavar=('SOURCE', 'TARGET'), help='Remove from TARGET profile dismiss entries matching SOURCE timestamps (e.g. test promo)')
    args = parser.parse_args()
    ref_path = PROFILES_DIR / args.reference / 'data' / 'personal.json'
    if not args.strip_peer and (not ref_path.is_file()):
        print(f'reference profile personal.json missing: {ref_path}', file=sys.stderr)
        return 1
    ref_maps: dict[str, dict[str, Any]] = {}
    if not args.strip_peer:
        ref_doc = _load_personal(ref_path)
        ref_personal = ref_doc.get('personal') or {}
        ref_maps = {k: ref_personal.get(k) or {} for k in BLEED_KEYS if isinstance(ref_personal.get(k), dict)}
    changed = 0
    if not args.strip_peer:
        for entry in sorted(PROFILES_DIR.iterdir()):
            if not entry.is_dir() or entry.name == args.reference:
                continue
            path = entry / 'data' / 'personal.json'
            if not path.is_file():
                continue
            doc = _load_personal(path)
            personal = doc.setdefault('personal', {})
            profile_maps = {k: personal.get(k) or {} for k in BLEED_KEYS if isinstance(personal.get(k), dict)}
            removed = _bleed_ids(ref_maps, profile_maps)
            if not removed:
                continue
            total = sum((len(v) for v in removed.values()))
            print(f'profiles/{entry.name}: would remove {total} inherited entries')
            for key, ids in removed.items():
                print(f'  {key}: {len(ids)} (sample {ids[:3]})')
            if args.apply:
                for key, ids in removed.items():
                    cur = personal.get(key)
                    if not isinstance(cur, dict):
                        continue
                    for cid in ids:
                        cur.pop(cid, None)
                backup = _backup(path)
                path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
                print(f'  applied (backup {backup.relative_to(ROOT)})')
            changed += 1
    if args.strip_peer:
        a_id, b_id = args.strip_peer
        a_path = PROFILES_DIR / a_id / 'data' / 'personal.json'
        b_path = PROFILES_DIR / b_id / 'data' / 'personal.json'
        if a_path.is_file() and b_path.is_file():
            a_doc = _load_personal(a_path)
            b_doc = _load_personal(b_path)
            b_personal = b_doc.setdefault('personal', {})
            a_maps = {k: (a_doc.get('personal') or {}).get(k) or {} for k in BLEED_KEYS}
            b_maps = {k: b_personal.get(k) or {} for k in BLEED_KEYS if isinstance(b_personal.get(k), dict)}
            removed = _bleed_ids(a_maps, b_maps)
            if removed:
                total = sum((len(v) for v in removed.values()))
                print(f'peer strip profiles/{b_id} vs profiles/{a_id}: {total} matching entries')
                if args.apply:
                    for key, ids in removed.items():
                        cur = b_personal.get(key)
                        if isinstance(cur, dict):
                            for cid in ids:
                                cur.pop(cid, None)
                    backup = _backup(b_path)
                    b_path.write_text(json.dumps(b_doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
                    print(f'  applied (backup {backup.relative_to(ROOT)})')
                    changed += 1
                else:
                    changed += 1
    if not changed:
        print('no bleed entries found on non-reference profiles')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())