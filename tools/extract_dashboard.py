"""One-off helper: extract dashboard section from app.js into dashboard.js.

DO NOT RUN — regex rewrites are unsafe after further refactors. Historical reference only.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
app_lines = (ROOT / "js" / "app.js").read_text(encoding="utf-8").splitlines()

ranges = [
    (1327, 1352),
    (1404, 1642),
    (1967, 2438),
]

body_lines: list[str] = []
for start, end in ranges:
    body_lines.extend(app_lines[start - 1 : end])

body = "\n".join(body_lines)

for name in (
    "getPersonal",
    "gameKey",
    "coverFallbackFor",
    "normalizeGame",
    "hltbMain",
    "ratingValue",
    "hasEnoughReviews",
    "getDealInfo",
    "itchIsGame",
    "wishlistGamesWithDeals",
    "dealScore",
    "isStealDeal",
    "dealHeroCardHtml",
    "dealHeroEmptyHtml",
    "dealSaleScoreboardCardHtml",
    "dealStealsCardHtml",
    "chipStatusKey",
    "gameGenresCanonical",
    "savePrefs",
    "switchView",
    "renderStoreChips",
    "refreshFilterUI",
    "renderGenreChips",
    "invalidateTableCache",
    "renderTable",
):
    body = re.sub(rf"\b{re.escape(name)}\(", f"c('{name}')(", body)

# Also rewrite bare references (function passed by value, e.g. .filter(fn))
for name in (
    "itchIsGame",
    "isStealDeal",
    "chipStatusKey",
    "hltbMain",
    "ratingValue",
    "hasEnoughReviews",
):
    body = re.sub(
        rf"(\.(?:filter|map|find|some|every|sort|reduce|forEach)\(\s*){re.escape(name)}(\s*[,)])",
        rf"\1c('{name}')\2",
        body,
    )

header = """import { state, STATUS_CHIP_DEFS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { renderDashboardFetcherHealth } from './fetcher-health.js';

let ctx = {};

export function initDashboard(appContext) {
  ctx = appContext;
}

function c(name) {
  const fn = ctx[name];
  if (!fn) throw new Error(`dashboard context missing: ${name}`);
  return fn;
}

"""

(ROOT / "js" / "dashboard.js").write_text(header + body + "\n", encoding="utf-8")
print(f"wrote js/dashboard.js ({len((header + body).splitlines())} lines)")
