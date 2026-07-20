# GOG Fetch: New Games Not Appearing in Recently Added — Diagnosis & Fix Plan

## Data Confirmed

- GOG `games_gog.json` went from **265 → 275** games (+10) on 2026-07-16 at ~11:31 AM PT
- Total BAKLOG library went from **~2059 → 2064** (+5 net-new)
- Source stayed **`local`** (Galaxy DB) — no source switch
- 5 of the 10 new GOG games were already in the library from other stores (cross-store duplicates)

## Full Ecosystem Audit

The "recently added" / first-seen system touches these surfaces. Every one was audited:

| Surface                      | File                                                               | Role                                                                    | Status                                                    |
| ---------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------- |
| **Core stamping**            | [`js/library-load.js:275`](js/library-load.js:275)                 | `recordLibraryFirstSeen()` — stamps new keys                            | Audited — should work for ≤7 games                        |
| **Snapshot**                 | [`js/library-load.js:207`](js/library-load.js:207)                 | `captureLibraryKeysBeforeMerge()` — snapshots prior keys                | Audited — possible double-call race                       |
| **Bulk repair**              | [`js/library-load.js:225`](js/library-load.js:225)                 | `repairBulkFirstSeenStamps()` — collapses ≥8 stamps at same second      | Audited — wouldn't affect 5 games                         |
| **Bulk threshold**           | [`js/library-load.js:215`](js/library-load.js:215)                 | `BULK_FIRST_SEEN_THRESHOLD = 8`                                         | Audited — 5 < 8, should pass                              |
| **Recents card**             | [`js/dashboard-spotlight.js:449`](js/dashboard-spotlight.js:449)   | `computeRecentAdditions()` — renders dashboard card                     | Audited — reads stamps correctly                          |
| **Recents render**           | [`js/dashboard-cards.js:329`](js/dashboard-cards.js:329)           | `renderDashboardRecentAdditions()` — DOM output                         | Audited                                                   |
| **+N flash**                 | [`js/dashboard.js:241`](js/dashboard.js:241)                       | Acquisition burst animation                                             | Audited — reads `_lastNewlyAddedCount`                    |
| **Metrics**                  | [`js/dashboard-insights.js:844`](js/dashboard-insights.js:844)     | `effectiveAddedMs()` — "newest add" metric                              | Audited — falls back to `added_at`                        |
| **Creative metrics**         | [`js/creative-metrics.js:49`](js/creative-metrics.js:49)           | `firstSeenAt()` — creative metric capsule                               | Audited                                                   |
| **Sabermetrics**             | [`js/sabermetrics.js:399`](js/sabermetrics.js:399)                 | `agingCurveBuckets()` — backlog aging                                   | Audited                                                   |
| **Persistence**              | [`js/personal-storage.js:40`](js/personal-storage.js:40)           | `loadLibraryFirstSeen()` / `saveLibraryFirstSeen()`                     | Audited                                                   |
| **Import/export**            | [`js/personal-storage.js:473`](js/personal-storage.js:473)         | Backup includes `libraryFirstSeen`                                      | Audited                                                   |
| **Supabase sync**            | [`js/personal-store.js:242`](js/personal-store.js:242)             | Server doc merge of `libraryFirstSeen`                                  | Audited                                                   |
| **Auto-enrich**              | [`js/fetcher-auto-refresh.js:208`](js/fetcher-auto-refresh.js:208) | `maybeAutoEnrichNewAdditions()` — triggers enrich after new games       | Audited — runs AFTER stamps, doesn't corrupt              |
| **`acquired_at` population** | Various fetchers                                                   | Only [`fetch_epic.py`](fetchers/fetch_epic.py:293) writes `acquired_at` | **Gap**: GOG, Steam, PSN, etc. do NOT populate this field |

## Honest Assessment

After thorough analysis: **the stamping code SHOULD work for 5 genuinely new games.** The `BULK_FIRST_SEEN_THRESHOLD` of 8 is not triggered. The `repairBulkFirstSeenStamps` path doesn't apply to <8 games. The enrich auto-fetch runs AFTER stamps are applied and doesn't corrupt them.

The most likely explanation is **environmental / one-time**:

- A race condition during that specific fetch session (concurrent reload, tab refresh mid-fetch, or SSE reconnect)
- localStorage state inconsistency (corrupted `libraryFirstSeenByKey` or `librarySeenSeeded` flag)
- The 5 games had pre-existing stamp 0 entries from a prior session (e.g., a previous GOG fetch that wrote them but crashed before stamping)

### Why we can't be certain without runtime data

The `games_gog.json` and `libraryFirstSeenByKey` are personal data not in the repo. To definitively diagnose:

1. We'd need the browser's `localStorage` `libraryFirstSeenByKey` dump
2. We'd need to diff the two `games_gog.json` backups to identify the 10 new GOG titles
3. We'd need to cross-reference with other store catalogs to find the 5 net-new ones

## Revised Solution Plan

### Phase 1: Non-invasive Diagnostics (do first)

These changes add observability without changing behavior:

#### 1a. Thread `mergeKey` through to `recordLibraryFirstSeen` for debug logging

In [`js/library-load.js`](js/library-load.js):

- Pass `mergeKey` from `applyMergedLibrary` to `recordLibraryFirstSeen`
- Add `isDebugEnabled()` gated console.debug that reports: mergeKey, new stamp count, priorKeyCount, pendingRealKeys sample, whether baselined

#### 1b. Add a `?debug=recents` query param that dumps `libraryFirstSeenByKey` state

In [`js/app.js`](js/app.js), when `?debug=recents` is set, expose `window.__baklogRecentsDebug` with:

- Full `libraryFirstSeenByKey` map
- Game keys with stamp 0 vs >0 grouped by store
- Recent additions sorted by timestamp

### Phase 2: Hardening (defense-in-depth)

These changes make the system more resilient, even if the root cause isn't confirmed:

#### 2a. Guard `captureLibraryKeysBeforeMerge` against double-call

```js
// js/library-load.js:207
export function captureLibraryKeysBeforeMerge() {
  if (state._libraryKeysBeforeMerge !== null) {
    if (isDebugEnabled()) {
      console.warn(
        "[baklog-recents] captureLibraryKeysBeforeMerge called while snapshot active - skipping",
      );
    }
    return;
  }
  // ... existing logic
}
```

This prevents a concurrent `reloadAllLibraryStoreFiles` (from an enrich fetcher completing) from overwriting the GOG fetch's snapshot.

**Risk**: If the second caller genuinely needs a fresh snapshot, it won't get one. But in practice, the first snapshot is always the one that matters — it represents the pre-fetch state. The second call (from an enrich reload) is redundant because the catalog data hasn't changed.

#### 2b. Add `acquired_at` population to GOG Galaxy client

In [`clients/gog_galaxy_client.py`](clients/gog_galaxy_client.py), read the `date_added` column from the Galaxy DB and surface it as `acquired_at`. This gives the frontend a fallback acquisition date from the source of truth.

#### 2c. Frontend: fall back to `acquired_at` when first-seen stamp is 0

In [`js/dashboard-spotlight.js`](js/dashboard-spotlight.js), modify `displayAddedAtForRecent` (line 439) to also consult `g.acquired_at`:

```js
function displayAddedAtForRecent(g, firstSeen) {
  if (firstSeen > 0) return firstSeen;
  const added = parseAddedAtMs(g);
  if (added > 0) return added;
  // NEW: fall back to catalog-side acquired_at
  const acq = g.acquired_at ? Date.parse(g.acquired_at) : 0;
  if (acq > 0) return acq;
  return null;
}
```

Also add the same fallback in [`js/creative-metrics.js:49`](js/creative-metrics.js:49) `firstSeenAt()` and [`js/dashboard-insights.js:844`](js/dashboard-insights.js:844) `effectiveAddedMs()`.

### Phase 3: Broader `acquired_at` coverage (future)

Only Epic currently populates `acquired_at`. Other stores that COULD provide this:

- **Steam**: License acquisition date is available via Steam API — already used for other metadata
- **PSN**: Purchase history API
- **Amazon**: Order date from Games & Software Library
- **itch.io**: Purchase/download date from API

This is lower priority — the Phase 2b change for GOG + the Phase 2c frontend fallback address the immediate gap.

## Targeted File Changes (Revised)

| File                                                             | Change                                                    | Phase | Risk                               |
| ---------------------------------------------------------------- | --------------------------------------------------------- | ----- | ---------------------------------- |
| [`js/library-load.js:207`](js/library-load.js:207)               | Guard double-snapshot in `captureLibraryKeysBeforeMerge`  | 2a    | Low — prevents snapshot corruption |
| [`js/library-load.js:275`](js/library-load.js:275)               | Add `mergeKey` param + debug logging                      | 1a    | None — debug-gated                 |
| [`js/library-load.js:383`](js/library-load.js:383)               | Pass `mergeKey` from `applyMergedLibrary`                 | 1a    | None                               |
| [`js/app.js`](js/app.js)                                         | Add `?debug=recents` diagnostics                          | 1b    | None — opt-in                      |
| [`clients/gog_galaxy_client.py`](clients/gog_galaxy_client.py)   | Read `date_added` → `acquired_at`                         | 2b    | Low — new field, backward-compat   |
| [`fetchers/fetch_gog.py:163`](fetchers/fetch_gog.py:163)         | Map `acquired_at` into game row                           | 2b    | Low                                |
| [`js/dashboard-spotlight.js:439`](js/dashboard-spotlight.js:439) | Fall back to `g.acquired_at` in `displayAddedAtForRecent` | 2c    | Low — additive fallback            |
| [`js/creative-metrics.js:49`](js/creative-metrics.js:49)         | Same `acquired_at` fallback                               | 2c    | Low                                |
| [`js/dashboard-insights.js:844`](js/dashboard-insights.js:844)   | Same `acquired_at` fallback                               | 2c    | Low                                |

## Verification

1. Run `python fetchers/fetch_gog.py --source local` with debug mode
2. Open dashboard with `?debug=1` and check console for `[baklog-recents]` output
3. Verify recents card shows the new GOG games
4. Run `window.__baklogRecentsDebug` in console (after Phase 1b) to inspect stamp state
