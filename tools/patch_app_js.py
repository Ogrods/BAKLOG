"""Patch app.js: wire extracted modules and remove duplicated blocks.

DO NOT RUN — line ranges are stale after module extraction. Historical reference only.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "js" / "app.js"
lines = path.read_text(encoding="utf-8").splitlines()

# Remove 1-based inclusive ranges (process high-to-low to preserve indices)
remove_ranges = [
    (4349, 4395),  # showMigrationBanner (duplicate)
    (1326, 2438),  # dashboard + fetcher health block
    (247, 415),    # personalStore inline
    (658, 666),    # escapeHtml, escapeAttr, formatNum
]

for start, end in sorted(remove_ranges, reverse=True):
    del lines[start - 1 : end]

text = "\n".join(lines) + "\n"

imports = """import { escapeHtml, escapeAttr, formatNum } from './dom-util.js';
import { personalStore, configurePersonalStore, showMigrationBanner } from './personal-store.js';
import { fetcherRunner, loadFetcherSources, renderDashboardFetcherHealth, configureFetcherHealth } from './fetcher-health.js';
import {
  initDashboard,
  scheduleDashboardRender,
  destroyDashboardCharts,
  dashboardLibraryGames,
  dashDrillCoop,
} from './dashboard.js';
"""

marker = "import { createMemo } from './memo.js';\n"
if marker not in text:
    raise SystemExit("import marker not found")
text = text.replace(marker, marker + "\n" + imports)

# Wire personal store after manualGames helpers
hook = "function removeManualGame(store, id) {\n"
insert = """configurePersonalStore({
  getManualGames: loadManualGames,
  setManualGames: (list) => { manualGames = list; },
});

"""
if hook not in text:
    raise SystemExit("manualGames hook not found")
text = text.replace(hook, insert + hook, 1)

# initDashboard before bootstrap - find reloadGames function end and add configureFetcherHealth
# Add initDashboard at start of bootstrap
bootstrap_hook = "async function bootstrap() {\n"
init_block = """async function bootstrap() {
  initDashboard({
    getPersonal,
    gameKey,
    coverFallbackFor,
    normalizeGame,
    hltbMain,
    ratingValue,
    hasEnoughReviews,
    getDealInfo,
    itchIsGame,
    wishlistGamesWithDeals,
    dealScore,
    isStealDeal,
    dealHeroCardHtml,
    dealHeroEmptyHtml,
    dealSaleScoreboardCardHtml,
    dealStealsCardHtml,
    chipStatusKey,
    gameGenresCanonical,
    savePrefs,
    switchView,
    renderStoreChips,
    refreshFilterUI,
    renderGenreChips,
    invalidateTableCache,
    renderTable,
  });
"""
text = text.replace(bootstrap_hook, init_block, 1)

# configureFetcherHealth after reloadGames - find "async function reloadGames"
reload_hook = "async function reloadGames() {"
fetcher_configure = """configureFetcherHealth({ reloadGames });
async function reloadGames() {"""
if reload_hook not in text:
    raise SystemExit("reloadGames not found")
text = text.replace(reload_hook, fetcher_configure, 1)

# loadFetcherSources in bootstrap before fetcherRunner.probeApi
probe_hook = "  fetcherRunner.probeApi().then(available => {"
load_sources = """  await loadFetcherSources();
  fetcherRunner.probeApi().then(available => {"""
text = text.replace(probe_hook, load_sources, 1)

# showMigrationBanner with onUploaded callback
banner_hook = "    showMigrationBanner(migrationInfo.pendingMigration);\n"
banner_new = """    showMigrationBanner(migrationInfo.pendingMigration, {
      escapeHtml,
      onUploaded: () => reloadGames().then(() => scheduleDashboardRender()),
    });
"""
text = text.replace(banner_hook, banner_new, 1)

path.write_text(text, encoding="utf-8")
print(f"patched {path} ({len(text.splitlines())} lines)")
