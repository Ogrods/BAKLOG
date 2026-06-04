#!/usr/bin/env python3
"""Backfill GOG release_date/genres cleared by a local/web source switch.

Idempotent: only fills fields that are empty in the current catalog when the
backup has a non-empty value. Writes via safe_write_text (rotated backup).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fetchers._base import catalog_file, write_catalog_text  # noqa: E402
from shared.json_util import dumps_games_json  # noqa: E402

DEFAULT_BACKUP = ROOT / "data/games_backups/games_gog/games_gog-20260603-163336-784.json"
CARRY_FIELDS = ("release_date", "genres")


def _is_empty(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _load_games(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    games = data.get("games") or []
    if not isinstance(games, list):
        games = []
    return data, [g for g in games if isinstance(g, dict)]


def main() -> int:
    backup_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BACKUP
    cur_path = catalog_file(Path("games_gog.json"))
    if not cur_path.is_file():
        print(f"ERROR: missing {cur_path}", file=sys.stderr)
        return 1
    if not backup_path.is_file():
        print(f"ERROR: missing backup {backup_path}", file=sys.stderr)
        return 1

    doc, games = _load_games(cur_path)
    _, backup_games = _load_games(backup_path)
    backup_by_id = {str(g["id"]): g for g in backup_games if g.get("id") is not None}

    patched = 0
    by_field: dict[str, int] = {}
    for g in games:
        gid = str(g.get("id"))
        old = backup_by_id.get(gid)
        if not old:
            continue
        for key in CARRY_FIELDS:
            if _is_empty(g.get(key)) and not _is_empty(old.get(key)):
                g[key] = old[key]
                patched += 1
                by_field[key] = by_field.get(key, 0) + 1

    if not patched:
        print("No empty fields to backfill — catalog already has metadata.")
        return 0

    doc["games"] = games
    doc["game_count"] = len(games)
    write_catalog_text(cur_path, dumps_games_json(doc))
    print(
        f"Restored {patched} field(s) on {cur_path.name} from {backup_path.name}: {by_field}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
