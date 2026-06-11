/** libraryGamesBase includes itch tab games in dashboard metrics. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('libraryGamesBase itch universe', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it('dashboardLibraryGames counts itch-only games', async () => {
    const { state } = await import('../js/state.js');
    const { dashboardLibraryGames } = await import('../js/dashboard-shared.js');
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
});
