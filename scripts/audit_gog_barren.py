#!/usr/bin/env python3
"""One-off audit: metadata-barren filter gaps in games_gog.json."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gog_filters import (  # noqa: E402
    dedupe_key,
    row_is_metadata_barren,
)


def prefix3(name: str) -> str:
    parts = re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split()
    return " ".join(parts[:3]) if len(parts) >= 3 else " ".join(parts)


def main() -> None:
    path = ROOT / "games_gog.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("games", rows)

    barren = [r for r in rows if row_is_metadata_barren(r)]
    populated = [r for r in rows if not row_is_metadata_barren(r)]

    print(f"Total rows: {len(rows)}")
    print(f"Barren (no cover AND no genres): {len(barren)}")
    print()

    print("=== ALL BARREN ROWS ===")
    for r in sorted(barren, key=lambda x: x.get("name", "")):
        print(f"  {r.get('gog_id')}: {r.get('name')}")
    print()

    groups = defaultdict(list)
    for r in rows:
        groups[dedupe_key(r.get("name") or "")].append(r)
    multi = {k: g for k, g in groups.items() if len(g) > 1 and k}
    print(f"dedupe_key groups with 2+ rows: {len(multi)}")
    for key, grp in sorted(multi.items())[:25]:
        print(f"  key={key!r}")
        for r in grp:
            b = "BARREN" if row_is_metadata_barren(r) else "ok"
            print(f"    [{b}] {r.get('name')} id={r.get('gog_id')}")
    print()

    pop_by_p3 = defaultdict(list)
    for r in populated:
        pop_by_p3[prefix3(r.get("name"))].append(r)

    def prefix2(name: str) -> str:
        parts = re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split()
        return " ".join(parts[:2]) if len(parts) >= 2 else " ".join(parts)

    pop_by_p2 = defaultdict(list)
    for r in populated:
        pop_by_p2[prefix2(r.get("name"))].append(r)

    print("=== BARREN with populated cousin (same 2-word prefix, DIFFERENT dedupe_key) ===")
    edition_gaps = 0
    for b in barren:
        cousins = pop_by_p2.get(prefix2(b.get("name")), [])
        if not cousins:
            continue
        edition_gaps += 1
        print(f"BARREN: {b.get('name')} gog_id={b.get('gog_id')}")
        print(f"  dedupe_key={dedupe_key(b.get('name') or '')!r}")
        for c in cousins:
            print(f"  cousin: {c.get('name')} gog_id={c.get('gog_id')}")
            print(f"    dedupe_key={dedupe_key(c.get('name') or '')!r}")
        print()

    print(f"Edition-variant gaps (barren + populated cousin, wrong key): {edition_gaps}")
    print()

    print("=== HAS COVER but empty genres (not barren; pack rule gap) ===")
    for r in sorted(rows, key=lambda x: x.get("name", "")):
        has_cover = bool((r.get("header_image") or "").strip())
        no_genres = not r.get("genres")
        if has_cover and no_genres:
            print(f"  {r.get('gog_id')}: {r.get('name')}")


if __name__ == "__main__":
    main()
