/** libraryGamesBase includes itch tab games in dashboard metrics. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('libraryGamesBase itch universe', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it('dashboardLibraryGames counts itch-only games', async () => {
    const { state } = await import('../js/state.js');
    const { setAuthStatusSnapshot } = await import('../js/connections-status.js');
    const { dashboardLibraryGames } = await import('../js/dashboard-shared.js');
    setAuthStatusSnapshot([{ key: 'itch_local', status: 'connected' }]);
    state.allGames = [];
    state.itchGames = [{
      name: 'Itch Solo',
      store: 'itch',
      id: 'itch-1',
      header_image: 'https://example.com/i.jpg',
    }];
    state.crossStoreHiddenKeys = new Set();
    state.personal = {};
    expect(dashboardLibraryGames()).toHaveLength(1);
  });

  it('dashboardLibraryGames excludes itch non-games (physical_game, assets, etc.)', async () => {
    const { state } = await import('../js/state.js');
    const { setAuthStatusSnapshot } = await import('../js/connections-status.js');
    const { dashboardLibraryGames } = await import('../js/dashboard-shared.js');
    setAuthStatusSnapshot([{ key: 'itch_local', status: 'connected' }]);
    state.allGames = [];
    state.itchGames = [
      {
        name: 'Real Game',
        store: 'itch',
        id: 'itch-game',
        classification: 'game',
        header_image: 'https://example.com/g.jpg',
      },
      {
        name: 'Physical Copy',
        store: 'itch',
        id: 'itch-physical',
        classification: 'physical_game',
        header_image: 'https://example.com/p.jpg',
      },
      {
        name: 'Asset Pack',
        store: 'itch',
        id: 'itch-assets',
        classification: 'assets',
        header_image: 'https://example.com/a.jpg',
      },
    ];
    state.crossStoreHiddenKeys = new Set();
    state.personal = {};
    expect(dashboardLibraryGames()).toHaveLength(1);
    expect(dashboardLibraryGames()[0].name).toBe('Real Game');
  });
});
