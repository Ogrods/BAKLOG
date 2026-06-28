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


def extract_script(html):
    m = re.search("<script>\\s*(.*?)\\s*</script>\\s*</body>", html, re.DOTALL)
    if not m:
        raise SystemExit("No inline <script> block found in index.html")
    lines = m.group(1).splitlines()
    return "\n".join(line[4:] if line.startswith("    ") else line for line in lines)


def rewrite_state_access(code):
    for field in STATE_FIELDS:
        code = re.sub(f"\\b{field}\\b", f"state.{field}", code)
    return code.replace("state.state.", "state.")


def build_state_js():
    return "export const STORAGE_KEY = 'steam-backlog-personal';\nexport const PREFS_KEY = 'steam-backlog-ui-prefs';\nexport const MANUAL_KEY = 'steam-backlog-manual-games';\n\nexport const state = {\n  allGames: [],\n  personal: {},\n  prefs: {},\n  sortKey: 'name',\n  sortDir: 1,\n  pickedKey: null,\n  libraryMeta: {\n    steam: null, gog: null, psn: null, epic: null, amazon: null, nintendo: null, itch: null,\n    wishlist: null,\n  },\n  crossStoreHiddenKeys: new Set(),\n  crossStoreOwnedStores: new Map(),\n  wishlistGames: [],\n  itchGames: [],\n  itadByKey: {},\n  activeView: 'dashboard',\n  selectedKeys: new Set(),\n  cleanupModeActive: false,\n  focusedRowIndex: -1,\n  ownedNormNames: new Set(),\n  filtersDrawerOpen: false,\n  genreChipsExpanded: false,\n};\n\nexport const CLEANUP_MAX_RATING = 60;\nexport const CLEANUP_MIN_AGE_MS = 2 * 365.25 * 24 * 60 * 60 * 1000;\nexport const GENRE_CHIP_COLLAPSE_AT = 12;\nexport const GENRE_ALIASES = { Simulator: 'Simulation', Sport: 'Sports' };\nexport const ITCH_NON_GAME_CLASSIFICATIONS = new Set([\n  'tool', 'assets', 'comic', 'book', 'soundtrack', 'physical_game', 'other',\n]);\nexport const STATUS_CHIP_DEFS = [\n  { key: 'backlog', label: 'Backlog' },\n  { key: 'next', label: 'Next' },\n  { key: 'playing', label: 'Playing' },\n  { key: 'unfinished', label: 'Unfinished' },\n  { key: 'live', label: 'Live' },\n  { key: 'finished', label: 'Finished' },\n  { key: 'skip', label: 'Skip' },\n];\nexport const STATUS_FILTER_LABELS = {\n  backlog: 'Backlog',\n  next: 'Next up',\n  playing: 'Playing',\n  unfinished: 'Unfinished',\n  live: 'Live service',\n  finished: 'Finished',\n  skip: 'Skip',\n  __none__: 'No status',\n};\n"


def main():
    html = INDEX.read_text(encoding="utf-8")
    body = extract_script(html)
    idx = body.find(PREAMBLE_END)
    if idx < 0:
        raise SystemExit("Could not find Constants section marker")
    app_body = body[idx:]
    app_body = rewrite_state_access(app_body)
    app_body = re.sub(
        "^let state\\.personal = loadPersonal\\(\\);\\s*\\nlet state\\.prefs = loadPrefs\\(\\);\\s*\\n",
        "",
        app_body,
        flags=re.MULTILINE,
    )
    app_body = app_body.replace("async function init()", "async function bootstrap()")
    app_body = re.sub("\\n\\s*init\\(\\);\\s*$", "", app_body)
    imports = "import {\n  state,\n  STORAGE_KEY,\n  PREFS_KEY,\n  MANUAL_KEY,\n  CLEANUP_MAX_RATING,\n  CLEANUP_MIN_AGE_MS,\n  GENRE_CHIP_COLLAPSE_AT,\n  GENRE_ALIASES,\n  ITCH_NON_GAME_CLASSIFICATIONS,\n  STATUS_CHIP_DEFS,\n  STATUS_FILTER_LABELS,\n} from './state.js';\n\nfunction hydrateState() {\n  state.personal = loadPersonal();\n  state.prefs = loadPrefs();\n}\n\n"
    bootstrap_tail = "\nhydrateState();\nbootstrap();\n"
    JS_DIR.mkdir(exist_ok=True)
    (JS_DIR / "state.js").write_text(build_state_js(), encoding="utf-8")
    (JS_DIR / "app.js").write_text(imports + app_body + bootstrap_tail, encoding="utf-8")
    new_html = re.sub(
        "<script>.*?</script>\\s*</body>",
        '  <script type="module" src="js/app.js"></script>\n</body>',
        html,
        count=1,
        flags=re.DOTALL,
    )
    INDEX.write_text(new_html, encoding="utf-8")
    print("Wrote js/state.js, js/app.js and patched index.html")


if __name__ == "__main__":
    main()
