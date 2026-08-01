import { describe, it, expect, beforeEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';

describe('dashboard clears #summary chips', () => {
  beforeEach(() => {
    vi.resetModules();
    hydrateIndexDocument();
  });

  it('empties #summary when switching to a cached dashboard', async () => {
    const dash = await import('../js/dashboard.js');
    vi.spyOn(dash, 'dashboardWasRendered').mockReturnValue(true);
    vi.spyOn(dash, 'renderDashboard').mockResolvedValue(undefined);
    vi.spyOn(dash, 'scheduleDashboardRender').mockImplementation(() => {});
    vi.spyOn(dash, 'cancelScheduledDashboardRender').mockImplementation(() => {});
    vi.spyOn(dash, 'stopDashboardRotations').mockImplementation(() => {});
    vi.spyOn(dash, 'setDashReplayAllowed').mockImplementation(() => {});

    const chart = await import('../js/chart-loader.js');
    vi.spyOn(chart, 'ensureChartJs').mockResolvedValue(undefined);

    const { state } = await import('../js/state.js');
    state.activeView = 'library';
    state.allGames = [];
    state.wishlistGames = [];
    state.itchGames = [];
    state.personal = {};
    state.prefs = {
      ...(state.prefs || {}),
      storeFilter: '',
      genreFilters: [],
      picksTab: 'topRated',
      libraryPicksTab: 'topRated',
    };
    state.sessionPrefs = { ...(state.sessionPrefs || {}), staleOnly: false, statusFilter: '' };
    state.selectedKeys = new Set();
    state.crossStoreHiddenKeys = new Set();
    state.wishlistCrossStoreHiddenKeys = new Set();

    const summary = document.getElementById('summary');
    expect(summary).toBeTruthy();
    summary.innerHTML = '<button type="button" class="summary-chip">Library chip</button>';

    const { switchView } = await import('../js/filters-ui.js');
    switchView('dashboard');

    expect(state.activeView).toBe('dashboard');
    expect(summary.innerHTML.trim()).toBe('');
    expect(summary.children.length).toBe(0);
  });
});
