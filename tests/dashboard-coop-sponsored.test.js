/** Co-op spotlight sponsored pick rows (Online + Couch). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

function coopGame(name, id, { rating = 95, online = true, local = false } = {}) {
  return {
    store: 'steam',
    id,
    name,
    coop_online: online,
    coop_local: local,
    steam_review_percent: rating,
    steam_review_count: 500,
    library_image: `https://example.com/${id}.jpg`,
  };
}

describe('dashboard co-op sponsored picks', () => {
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    win.document.body.innerHTML = '<div id="dashboardCoopSpotlight"></div>';

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    state.prefs = {};
    state.personal = Object.fromEntries(
      Array.from({ length: 6 }, (_, i) => [`steam:o${i}`, { status: 'backlog' }])
        .concat(Array.from({ length: 6 }, (_, i) => [`steam:c${i}`, { status: 'backlog' }])),
    );
    state.sponsoredDeals = [
      {
        id: 'ad-coop-online-zephyr',
        kind: 'sponsor',
        title: 'Zephyr Edge',
        tagline: 'Blistering arcade racer',
        cta: 'View deal',
        url: 'https://example.com/z',
        cover: '/assets/ads-sample/cover-zephyr-edge.webp',
        placements: 'coop-online',
        priority: 1,
        enabled: true,
        steam_review_percent: 96,
      },
      {
        id: 'ad-coop-couch-ironveil',
        kind: 'sponsor',
        title: 'Ironveil',
        tagline: 'Couch co-op dungeon crawler',
        cta: 'View deal',
        url: 'https://example.com/i',
        cover: '/assets/ads-sample/cover-ironveil.webp',
        placements: 'coop-couch',
        priority: 1,
        enabled: true,
        steam_review_percent: 93,
      },
    ];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows Zephyr on Online co-op and Ironveil on Couch co-op as the last pick', async () => {
    const authGate = await import('../js/auth-gate.js');
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    const { renderDashboardCoopSpotlight } = await import('../js/dashboard-cards.js');
    const onlineGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Online ${i}`, `o${i}`, { rating: 98 - i, online: true, local: false }),
    );
    const couchGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Couch ${i}`, `c${i}`, { rating: 97 - i, online: false, local: true }),
    );
    const games = [...onlineGames, ...couchGames];
    renderDashboardCoopSpotlight(games);

    const onlineList = document.querySelector('.coop-side-online .coop-side-picks-list');
    const couchList = document.querySelector('.coop-side-local .coop-side-picks-list');
    const onlineLast = onlineList.lastElementChild;
    const couchLast = couchList.lastElementChild;
    expect(onlineLast.classList.contains('sponsored-coop-row')).toBe(true);
    expect(couchLast.classList.contains('sponsored-coop-row')).toBe(true);
    expect(onlineLast.textContent).toContain('Zephyr Edge');
    expect(couchLast.textContent).toContain('Ironveil');
    expect(onlineList.querySelectorAll('.coop-pick-row:not(.sponsored-coop-row)').length).toBe(2);
    expect(couchList.querySelectorAll('.coop-pick-row:not(.sponsored-coop-row)').length).toBe(2);
    expect(onlineLast.querySelector('[data-action="sponsored-dismiss"]')).toBeTruthy();
  });

  it('dismiss restores the 3rd-rated pick on that side only', async () => {
    const authGate = await import('../js/auth-gate.js');
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    const { renderDashboardCoopSpotlight } = await import('../js/dashboard-cards.js');
    const { dismissSponsoredDeal, __resetDismissedSponsorsForTest } = await import('../js/sponsored-deals.js');
    __resetDismissedSponsorsForTest();
    const onlineGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Online ${i}`, `o${i}`, { rating: 98 - i, online: true, local: false }),
    );
    const couchGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Couch ${i}`, `c${i}`, { rating: 97 - i, online: false, local: true }),
    );
    renderDashboardCoopSpotlight([...onlineGames, ...couchGames]);

    dismissSponsoredDeal('ad-coop-online-zephyr');
    renderDashboardCoopSpotlight([...onlineGames, ...couchGames]);

    const onlineList = document.querySelector('.coop-side-online .coop-side-picks-list');
    const couchList = document.querySelector('.coop-side-local .coop-side-picks-list');
    const onlineLast = onlineList.lastElementChild;
    expect(onlineLast.classList.contains('sponsored-coop-row')).toBe(false);
    expect(onlineLast.dataset.key).toBe('steam:o2');
    expect(onlineList.querySelectorAll('.coop-pick-row:not(.sponsored-coop-row)').length).toBe(3);
    expect(couchList.lastElementChild.classList.contains('sponsored-coop-row')).toBe(true);
    expect(couchList.lastElementChild.textContent).toContain('Ironveil');
  });

  it('surgical swap replaces only the ad row, leaving sibling rows untouched', async () => {
    const authGate = await import('../js/auth-gate.js');
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    const { renderDashboardCoopSpotlight, replaceCoopSponsorRow } = await import('../js/dashboard-cards.js');
    const onlineGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Online ${i}`, `o${i}`, { rating: 98 - i, online: true, local: false }),
    );
    const couchGames = Array.from({ length: 4 }, (_, i) =>
      coopGame(`Couch ${i}`, `c${i}`, { rating: 97 - i, online: false, local: true }),
    );
    const games = [...onlineGames, ...couchGames];
    renderDashboardCoopSpotlight(games);

    const onlineList = document.querySelector('.coop-side-online .coop-side-picks-list');
    const couchList = document.querySelector('.coop-side-local .coop-side-picks-list');
    // Capture node identity of rows that must NOT be recreated (no cover reload).
    const keptOnlineRows = [onlineList.children[0], onlineList.children[1]];
    const keptCouchRows = [...couchList.children];

    const handled = replaceCoopSponsorRow('ad-coop-online-zephyr', games);
    expect(handled).toBe(true);

    // Surviving rows are the *same* DOM nodes (never re-rendered).
    expect(onlineList.children[0]).toBe(keptOnlineRows[0]);
    expect(onlineList.children[1]).toBe(keptOnlineRows[1]);
    expect([...couchList.children]).toEqual(keptCouchRows);
    // The ad row became the displaced 3rd-rated online pick.
    const onlineLast = onlineList.lastElementChild;
    expect(onlineLast.classList.contains('sponsored-coop-row')).toBe(false);
    expect(onlineLast.dataset.key).toBe('steam:o2');
    expect(onlineList.querySelectorAll('.coop-pick-row:not(.sponsored-coop-row)').length).toBe(3);
    // Unknown id is not handled (caller falls back to full render).
    expect(replaceCoopSponsorRow('nope', games)).toBe(false);
  });
});
