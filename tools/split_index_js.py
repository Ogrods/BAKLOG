#!/usr/bin/env python3
"""Extract index.html inline script into js/state.js + js/app.js (Phase 0)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
JS_DIR = ROOT / "js"

STATE_FIELDS = [
    "allGames",
    "personal",
    "prefs",
    "sortKey",
    "sortDir",
    "pickedKey",
    "libraryMeta",
    "crossStoreHiddenKeys",
    "crossStoreOwnedStores",
    "wishlistGames",
    "itchGames",
    "itadByKey",
    "activeView",
    "selectedKeys",
    "cleanupModeActive",
    "focusedRowIndex",
    "ownedNormNames",
    "filtersDrawerOpen",
    "genreChipsExpanded",
]

PREAMBLE_END = "// === Constants & config ==="


def extract_script(html: str) -> str:
    m = re.search(r"<script>\s*(.*?)\s*</script>\s*</body>", html, re.DOTALL)
    if not m:
        raise SystemExit("No inline <script> block found in index.html")
    lines = m.group(1).splitlines()
    return "\n".join(line[4:] if line.startswith("    ") else line for line in lines)


def rewrite_state_access(code: str) -> str:
    for field in STATE_FIELDS:
        code = re.sub(rf"\b{field}\b", f"state.{field}", code)
    return code.replace("state.state.", "state.")


def build_state_js() -> str:
    return """export const STORAGE_KEY = 'steam-backlog-personal';
export const PREFS_KEY = 'steam-backlog-ui-prefs';
export const MANUAL_KEY = 'steam-backlog-manual-games';

export const state = {
  allGames: [],
  personal: {},
  prefs: {},
  sortKey: 'name',
  sortDir: 1,
  pickedKey: null,
  libraryMeta: { steam: null, gog: null, psn: null, epic: null, amazon: null, nintendo: null, itch: null, wishlist: null },
  crossStoreHiddenKeys: new Set(),
  crossStoreOwnedStores: new Map(),
  wishlistGames: [],
  itchGames: [],
  itadByKey: {},
  activeView: 'dashboard',
  selectedKeys: new Set(),
  cleanupModeActive: false,
  focusedRowIndex: -1,
  ownedNormNames: new Set(),
  filtersDrawerOpen: false,
  genreChipsExpanded: false,
};

export const CLEANUP_MAX_RATING = 60;
export const CLEANUP_MIN_AGE_MS = 2 * 365.25 * 24 * 60 * 60 * 1000;
export const GENRE_CHIP_COLLAPSE_AT = 12;
export const GENRE_ALIASES = { Simulator: 'Simulation', Sport: 'Sports' };
export const ITCH_NON_GAME_CLASSIFICATIONS = new Set(['tool', 'assets', 'comic', 'book', 'soundtrack', 'physical_game', 'other']);
export const STATUS_CHIP_DEFS = [
  { key: 'backlog', label: 'Backlog' },
  { key: 'next', label: 'Next' },
  { key: 'playing', label: 'Playing' },
  { key: 'unfinished', label: 'Unfinished' },
  { key: 'live', label: 'Live' },
  { key: 'finished', label: 'Finished' },
  { key: 'skip', label: 'Skip' },
];
export const STATUS_FILTER_LABELS = {
  backlog: 'Backlog',
  next: 'Next up',
  playing: 'Playing',
  unfinished: 'Unfinished',
  live: 'Live service',
  finished: 'Finished',
  skip: 'Skip',
  __none__: 'No status',
};
"""


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")
    body = extract_script(html)
    idx = body.find(PREAMBLE_END)
    if idx < 0:
        raise SystemExit("Could not find Constants section marker")
    app_body = body[idx:]

    app_body = rewrite_state_access(app_body)
    app_body = re.sub(
        r"^let state\.personal = loadPersonal\(\);\s*\nlet state\.prefs = loadPrefs\(\);\s*\n",
        "",
        app_body,
        flags=re.MULTILINE,
    )
    app_body = app_body.replace("async function init()", "async function bootstrap()")
    app_body = re.sub(r"\n\s*init\(\);\s*$", "", app_body)

    imports = """import {
  state,
  STORAGE_KEY,
  PREFS_KEY,
  MANUAL_KEY,
  CLEANUP_MAX_RATING,
  CLEANUP_MIN_AGE_MS,
  GENRE_CHIP_COLLAPSE_AT,
  GENRE_ALIASES,
  ITCH_NON_GAME_CLASSIFICATIONS,
  STATUS_CHIP_DEFS,
  STATUS_FILTER_LABELS,
} from './state.js';

function hydrateState() {
  state.personal = loadPersonal();
  state.prefs = loadPrefs();
}

"""

    bootstrap_tail = """
hydrateState();
bootstrap();
"""

    JS_DIR.mkdir(exist_ok=True)
    (JS_DIR / "state.js").write_text(build_state_js(), encoding="utf-8")
    (JS_DIR / "app.js").write_text(imports + app_body + bootstrap_tail, encoding="utf-8")

    new_html = re.sub(
        r"<script>.*?</script>\s*</body>",
        '  <script type="module" src="js/app.js"></script>\n</body>',
        html,
        count=1,
        flags=re.DOTALL,
    )
    INDEX.write_text(new_html, encoding="utf-8")
    print("Wrote js/state.js, js/app.js and patched index.html")


if __name__ == "__main__":
    main()
