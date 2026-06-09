/**
 * Manual verification matrix for propagation instrumentation (Phase 4).
 * Enable ?debug=1 and compare window.__baklogProp (+ overlay `prop` row)
 * after each scenario. Vitest asserts hooks exist at documented call sites.
 */

/** @typedef {{ min?: number, max?: number, exact?: number }} CounterExpect */

/**
 * @typedef {object} PropagationScenario
 * @property {string} id
 * @property {string} title
 * @property {string} trigger
 * @property {string} activeView
 * @property {Record<string, CounterExpect>} expect
 * @property {string[]} hooks — source needles that must exist
 */

/** @type {PropagationScenario[]} */
export const PROPAGATION_SCENARIOS = [
  {
    id: 'fetcher-library',
    title: 'Library fetcher completes while on Library',
    trigger: 'SSE done → refreshAfterFetch → reloadAfterFetcher → applyMergedLibrary',
    activeView: 'library',
    expect: { fetcherReloads: { min: 1 }, merges: { min: 1 }, tableRenders: { min: 1 } },
    hooks: ['noteFetcherReload', 'noteLibraryMerge', 'noteTableRender'],
  },
  {
    id: 'fetcher-connections',
    title: 'Fetcher completes while on Connections (deferred table)',
    trigger: 'applyMergedLibrary → refreshFilterUI defers table paint',
    activeView: 'connections',
    expect: { merges: { min: 1 }, deferredDefers: { min: 1 }, tableRenders: { exact: 0 } },
    hooks: ['noteDeferredDefer', 'deferTableRender'],
  },
  {
    id: 'connections-to-library',
    title: 'Switch Connections → Library after deferred fetch',
    trigger: 'switchView → flushDeferredRenders → renderTable',
    activeView: 'library',
    expect: { deferredFlushes: { min: 1 }, tableRenders: { min: 1 } },
    hooks: ['flushDeferredRenders', 'noteDeferredFlush'],
  },
  {
    id: 'fetcher-dashboard',
    title: 'Fetcher completes while on Dashboard',
    trigger: 'applyMergedLibrary → scheduleDashboardRender (see dash row F:)',
    activeView: 'dashboard',
    expect: { merges: { min: 1 }, tableRenders: { exact: 0 } },
    hooks: ['noteLibraryMerge', 'scheduleDashboardRender'],
  },
  {
    id: 'enrich-protondb',
    title: 'ProtonDB enrich completes',
    trigger: 'reloadAfterFetcher(protondb) → loadProtondbCache → applyMergedLibrary',
    activeView: 'library',
    expect: { fetcherReloads: { min: 1 }, merges: { min: 1 } },
    hooks: ['loadProtondbCache', 'noteFetcherReload'],
  },
  {
    id: 'enrich-steam-tags',
    title: 'Steam tags enrich (no wishlist bulk reload)',
    trigger: 'reloadAfterFetcher(steamTags) — ENRICH_RELOAD_WISHLIST_KEYS excludes key',
    activeView: 'library',
    expect: { fetcherReloads: { min: 1 }, merges: { min: 1 } },
    hooks: ['ENRICH_RELOAD_WISHLIST_KEYS', 'steamTags'],
  },
  {
    id: 'personal-status',
    title: 'Personal status change (row action)',
    trigger: 'savePersonal → scheduleDownstreamSync (200ms debounce)',
    activeView: 'library',
    expect: { downstreamSyncs: { min: 1 } },
    hooks: ['scheduleDownstreamSync', 'noteDownstreamSync'],
  },
  {
    id: 'cross-tab-personal',
    title: 'Other tab writes personal JSON (storage event)',
    trigger: 'installPersonalStorageSync → scheduleDownstreamSync',
    activeView: 'library',
    expect: { downstreamSyncs: { min: 1 } },
    hooks: ['installPersonalStorageSync', 'scheduleDownstreamSync'],
  },
  {
    id: 'fingerprint-skip',
    title: 'Repeated render with unchanged fingerprint',
    trigger: 'renderTable without force — fingerprint cache hit',
    activeView: 'library',
    expect: { tableSkips: { min: 1 } },
    hooks: ['noteTableRenderSkipped'],
  },
  {
    id: 'manual-reload',
    title: 'Manual Reload library button',
    trigger: 'reloadGames → applyMergedLibrary',
    activeView: 'library',
    expect: { merges: { min: 1 } },
    hooks: ['applyMergedLibrary', 'noteLibraryMerge'],
  },
];
