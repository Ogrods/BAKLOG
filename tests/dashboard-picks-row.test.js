/** Dashboard picks row layout — itch visibility, recents card, sponsored versus rows. */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

const INDEX_HTML = readFileSync(join(import.meta.dirname, '..', 'index.html'), 'utf8');

function backlogGame(name, id, { rating = 92, hltb = 8 } = {}) {
  return {
    store: 'steam',
    id,
    name,
    steam_review_percent: rating,
    steam_review_count: 500,
    library_image: `https://example.com/${id}.jpg`,
    hltb_main_hours: hltb,
  };
}

describe('dashboard picks row', () => {
  let applyItchVisibility;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    win.document.body.innerHTML = `
      <div id="dashboardPicksRow" class="dash-picks-row">
        <div id="dashPicksVersusCard" class="dash-picks-versus">
          <div id="dashVersusRated" class="dash-versus-list"></div>
          <div id="dashVersusFast" class="dash-versus-list"></div>
          <span id="dashVersusBadge" class="hidden"></span>
        </div>
        <div id="dashItchCard" class="dash-card-itch"></div>
        <div id="dashRecentCard" class="dash-recent-card">
          <div id="dashRecentAdditions" class="dash-recent-list"></div>
        </div>
      </div>`;

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ applyItchVisibility } = await import('../js/dashboard-cards.js'));
    state.itchGames = [];
    state.prefs = { quickWinMaxHours: 15 };
    state.personal = {
      'steam:a': { status: 'backlog' },
      'steam:b': { status: 'backlog' },
    };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('ships index.html with itch hidden by default until library data exists', () => {
    const picksRow = INDEX_HTML.match(/<div[^>]*id="dashboardPicksRow"[^>]*>/)?.[0] ?? '';
    const itchCard = INDEX_HTML.match(/<div[^>]*id="dashItchCard"[^>]*>/)?.[0] ?? '';
    const itchTab = INDEX_HTML.match(/<button[^>]*data-view="itch"[^>]*>/)?.[0] ?? '';
    expect(picksRow).toMatch(/\bno-itch\b/);
    expect(itchCard).toMatch(/\bhidden\b/);
    expect(itchTab).toMatch(/\bhidden\b/);
  });

  it('shows recents card and no-itch when itch library is empty', () => {
    applyItchVisibility();
    const row = document.getElementById('dashboardPicksRow');
    const itch = document.getElementById('dashItchCard');
    const recent = document.getElementById('dashRecentCard');
    expect(row.classList.contains('no-itch')).toBe(true);
    expect(itch.classList.contains('hidden')).toBe(true);
    expect(recent.classList.contains('hidden')).toBe(false);
  });

  it('removes no-itch and shows itch card when itch data exists', () => {
    state.itchGames = [{ store: 'itch', id: 'a', name: 'Demo' }];
    applyItchVisibility();
    const row = document.getElementById('dashboardPicksRow');
    const itch = document.getElementById('dashItchCard');
    expect(row.classList.contains('no-itch')).toBe(false);
    expect(itch.classList.contains('hidden')).toBe(false);
  });

  it('appends two distinct sponsored rows to rated and fast columns', async () => {
    const authGate = await import('../js/auth-gate.js');
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    const { renderDashboardPicksVersus } = await import('../js/dashboard-cards.js');
    const { __setSponsorsForTest } = await import('../js/sponsored-deals.js');
    __setSponsorsForTest({
      version: 2,
      ads: {
        'ad-dash-rated': {
          kind: 'sponsor',
          title: 'Dawnbanner',
          tagline: 'Trending tactical RPG',
          cta: 'View deal',
          url: 'https://example.com/dawn',
          cover: '/assets/ads-sample/hero-dawnbanner.webp',
          enabled: true,
          steam_review_percent: 94,
          hltb_hours: 32,
        },
        'ad-dash-fast': {
          kind: 'house',
          title: 'Emberfall',
          tagline: 'Open-world adventure',
          cta: 'View deal',
          url: 'https://example.com/ember',
          cover: '/assets/ads-sample/cover-encore.webp',
          enabled: true,
          hltb_hours: 10,
        },
      },
      locations: {
        'dash-versus-rated': ['ad-dash-rated'],
        'dash-versus-fast': ['ad-dash-fast'],
      },
    });
    const games = [
      backlogGame('Alpha Game', 'a', { rating: 95, hltb: 6 }),
      backlogGame('Beta Game', 'b', { rating: 88, hltb: 12 }),
    ];
    renderDashboardPicksVersus(games);

    const rated = document.getElementById('dashVersusRated');
    const fast = document.getElementById('dashVersusFast');
    const ratedSponsor = rated.lastElementChild;
    const fastSponsor = fast.lastElementChild;
    expect(ratedSponsor.classList.contains('sponsored-versus-row')).toBe(true);
    expect(fastSponsor.classList.contains('sponsored-versus-row')).toBe(true);
    expect(ratedSponsor.textContent).toContain('Dawnbanner');
    expect(fastSponsor.textContent).toContain('Emberfall');
    expect(ratedSponsor.querySelector('.text-slate-400')?.textContent).toMatch(/%$/);
    expect(fastSponsor.querySelector('.text-slate-400')?.textContent).toMatch(/h$/);
    expect(ratedSponsor.querySelector('[data-action="sponsored-dismiss"]')).toBeTruthy();
    expect(fastSponsor.querySelector('[data-action="sponsored-dismiss"]')).toBeTruthy();

    // Disclosure badge renders AFTER the title (its previous sibling is the title).
    const badge = ratedSponsor.querySelector('.sponsored-versus-badge');
    expect(badge).toBeTruthy();
    expect(badge.previousElementSibling?.classList.contains('truncate')).toBe(true);
  });

  it('X-ing out a column ad restores the displaced game in that slot', async () => {
    const authGate = await import('../js/auth-gate.js');
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    const { renderDashboardPicksVersus } = await import('../js/dashboard-cards.js');
    const { dismissSponsoredDeal, __resetDismissedSponsorsForTest } = await import('../js/sponsored-deals.js');
    __resetDismissedSponsorsForTest();
    // itch present => maxPicks caps each column at 5 rows; ad displaces the last slot.
    state.itchGames = [{ store: 'itch', id: 'x', name: 'X' }];
    state.personal = Object.fromEntries(
      Array.from({ length: 7 }, (_, i) => [`steam:g${i}`, { status: 'backlog' }]),
    );
    const { __setSponsorsForTest } = await import('../js/sponsored-deals.js');
    __setSponsorsForTest({
      version: 2,
      ads: {
        'ad-dash-rated': { kind: 'sponsor', title: 'Dawnbanner', tagline: 't', cta: 'c', url: 'https://example.com/d', cover: '/a.webp', enabled: true },
        'ad-dash-fast': { kind: 'house', title: 'Emberfall', tagline: 't', cta: 'c', url: 'https://example.com/e', cover: '/b.webp', enabled: true },
      },
      locations: {
        'dash-versus-rated': ['ad-dash-rated'],
        'dash-versus-fast': ['ad-dash-fast'],
      },
    });
    const games = Array.from({ length: 7 }, (_, i) =>
      backlogGame(`Game ${i}`, `g${i}`, { rating: 99 - i, hltb: i + 1 }),
    );
    renderDashboardPicksVersus(games);

    const rated = document.getElementById('dashVersusRated');
    expect(rated.lastElementChild.classList.contains('sponsored-versus-row')).toBe(true);
    expect(rated.querySelectorAll('.dash-list-row:not(.sponsored-versus-row)').length).toBe(4);

    dismissSponsoredDeal('ad-dash-rated');
    renderDashboardPicksVersus(games);

    const last = rated.lastElementChild;
    expect(last.classList.contains('sponsored-versus-row')).toBe(false);
    expect(last.getAttribute('data-action')).toBe('dash-list-jump');
    expect(last.dataset.key).toBe('steam:g4');
    expect(rated.querySelectorAll('.dash-list-row:not(.sponsored-versus-row)').length).toBe(5);
    // Fast column keeps its own ad (only the rated ad was dismissed).
    const fast = document.getElementById('dashVersusFast');
    expect(fast.lastElementChild.classList.contains('sponsored-versus-row')).toBe(true);
    expect(fast.lastElementChild.textContent).toContain('Emberfall');
  });
});
