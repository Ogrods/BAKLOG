import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('renderPicks custom lists', () => {
  let renderPicks;
  let effectivePicksTab;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    win.document.body.innerHTML = `
      <div id="pickMeta"></div>
      <div id="picksGrid"></div>
      <div id="quickWinMaxWrap" class="hidden"></div>
      <div id="viewHouseSlot" class="hidden"></div>
      <button class="pick-tab" data-tab="customList0" data-pick-view="library"></button>
    `;

    vi.resetModules();
    vi.stubGlobal('coverLandscapeAttr', () => '');
    vi.stubGlobal('markLandscape', () => {});
    vi.stubGlobal('coverFallback', () => {});

    ({ state } = await import('../js/state.js'));
    state.activeView = 'library';
    state.prefs = {
      picksTab: 'customList0',
      viewPicksLimits: { library: 16 },
      customLists: [
        { name: 'Mine', keys: ['steam:2', 'steam:1'] },
        { name: 'List 2', keys: [] },
        { name: 'List 3', keys: [] },
      ],
    };
    state.allGames = [
      { store: 'steam', id: '1', name: 'Alpha', steam_review_percent: 90 },
      { store: 'steam', id: '2', name: 'Beta', steam_review_percent: 80, library_image: 'http://example.com/b.png' },
    ];
    state.wishlistGames = [];
    state.itchGames = [];
    state.crossStoreHiddenKeys = new Set();
    state.personal = {};

    const sponsored = await import('../js/sponsored-deals.js');
    vi.spyOn(sponsored, 'sponsoredPickSlotHtml').mockReturnValue('');
    vi.spyOn(sponsored, 'renderHouseLocationSlot').mockImplementation(() => {});

    ({ renderPicks, effectivePicksTab } = await import('../js/picks-ui.js'));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders custom list games in stored order without sponsor slot', () => {
    renderPicks();
    const cards = document.querySelectorAll('.pick-card:not(.sponsored-pick-card)');
    expect(cards).toHaveLength(2);
    expect(cards[0].dataset.gameKey).toBe('steam:2');
    expect(cards[1].dataset.gameKey).toBe('steam:1');
    expect(document.querySelector('.sponsored-pick-card')).toBeNull();
    expect(document.getElementById('pickMeta').textContent).toBe('2 of 2');
  });

  it('shows custom list empty state message', () => {
    state.prefs.customLists[0].keys = [];
    state.prefs.picksTab = 'customList0';
    renderPicks();
    expect(document.getElementById('picksGrid').textContent).toContain('Add to list');
  });

  it('effectivePicksTab falls back from hidden custom tab', () => {
    state.prefs.picksTab = 'customList0';
    state.prefs.libraryPicksTab = 'quickWins';
    state.prefs.customLists[0].keys = [];
    state.prefs.customLists[0].name = 'List 1';
    expect(effectivePicksTab()).toBe('quickWins');
  });

  it('respects picks limit slice on custom lists', () => {
    state.prefs.viewPicksLimits = { library: 16 };
    state.prefs.customLists[0].keys = ['steam:1', 'steam:2'];
    renderPicks();
    expect(document.querySelectorAll('.pick-card')).toHaveLength(2);
    expect(document.getElementById('pickMeta').textContent).toBe('2 of 2');
  });
});
