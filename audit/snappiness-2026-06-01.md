# UI snappiness audit — 2026-06-01

**Method:** Code-path review + existing `?perf=1` instrumentation ([js/table-perf.js](../js/table-perf.js)). Re-run in browser with `?perf=1` (not `?debug=1`) and fill **Measured ms** after shipping fixes.

**Baseline:** post tag-rip-out (`f45353b`), dashboard files at `c940c26` perf behavior.

## Findings (pre-fix)

| # | Surface | Trigger | Est. total ms | Long-task source | Risk | Action |
|---|---------|---------|---------------|------------------|------|--------|
| 1 | Cold boot | Hard refresh → dashboard | 800–2500 | `reloadGames`, fetcher probe, Chart.js parse (blocking `defer` script) | Low | Lazy-load Chart.js; boot curtain already masks |
| 2 | Cold boot → library | Tab switch uncached | 200–600 | `queryGamesAsync` + first `paintTableBody` virtual window | Low | Row loader; query cache |
| 3 | Library search | One character in search | 80–250 | Filter+sort in worker/main; debounce already 120ms | Low | Confirmed `refreshFilterUIDebounced` @ 120ms |
| 4 | Sort click | Score / Price header | 50–180 | Sync virtual repaint + `renderSortIndicators` | Low | Header arrow reserve width (alignment) |
| 5 | Status chip | Filter pill | 80–200 | Full table query + paint | Low | Row loader |
| 6 | Genre / store | Chip toggle | 100–300 | `renderSummary` + `renderTable` | Med | Defer summary on idle paths already partial |
| 7 | Drill-down | Dashboard chart → library | 150–400 | Drill defers summary/picks via `requestIdleCallback` | Low | Keep; row loader on `renderTable` |
| 8 | Tab switch | Wishlist → library uncached | 200–500 | Query + paint | Low | Prewarm wishlist query on idle when on library |
| 9 | Tab switch | Library → wishlist cached | &lt;50 | Fingerprint cache hit | — | None |
| 10 | Notes drawer | Open / close | &lt;30 | DOM only | — | None |
| 11 | Picks | Tab change | 40–120 | `renderPicks` deal scan | Low | `skipPicks` on search already |
| 12 | CSV export | Export click | 50–400+ | Sync string build ∝ row count | Med | Deferred (separate plan) |
| 13 | Dashboard cold | First full paint | 400–1200 | Many Chart.js entrance anims + below-fold sections | Low | Defer wishlist/coop/picks sections via idle |
| 14 | Debug overlay | `?debug=1` always on | +5–15% CPU | 500ms poll: `tableFingerprint`, `countOrphanPersonalKeys` | Low | Poll 1000ms; skip orphans when overlay hidden |

**Must-fix (&gt;250ms perceived):** 1 (library boot path), 6 (heavy genre), 12 (large libraries) — loader + defer address 1–8 perception; 12 out of scope.

## Shipped in this pass

- [js/row-loader.js](../js/row-loader.js) — 120ms threshold spinner on `#tableShell`
- [js/chart-loader.js](../js/chart-loader.js) — dynamic Chart.js when dashboard needed
- Dashboard below-fold defer (`requestIdleCallback`)
- Debug overlay poll 1000ms; orphans only when panel visible
- CSS `contain: layout paint` on `#tableShell`, `#dashboardContainer`
- `prefers-reduced-motion` for row-loader + Chart defaults
- `prewarmTableQueryForView('wishlist')` on idle when library active
- Sort headers: always show ↕, fixed arrow width

## After (fill in manually)

| # | Measured ms (post) | Notes |
|---|-------------------|-------|
| 1 | | |
| 2 | | |
| 3 | | |
| … | | |
