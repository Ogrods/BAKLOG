import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 0),
  isStealDeal: vi.fn(() => false),
  cutBucketClass: vi.fn(() => 'cut-low'),
  computeWishlistWoba: vi.fn(() => null),
  isCleanupCandidate: vi.fn(() => false),
  parsePriceLike: vi.fn((v) => {
    if (v == null) return null;
    if (typeof v === 'number') return v;
    const m = String(v).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }),
}));

import { state } from '../js/state.js';
import { buildMarqueeItems, renderMarqueeHtml } from '../js/dashboard-insights.js';
import { applyMarqueeSpeed, MARQUEE_PX_PER_SEC } from '../js/marquee-speed.js';
import { marqueeTip } from '../js/metric-tips.js';
import { getLibrarySnapshot, invalidateLibrarySnapshot } from '../js/sabermetrics.js';

function game(overrides = {}) {
  return {
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    steam_review_count: overrides.steam_review_count ?? 100,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    playtime_minutes: overrides.playtime_minutes ?? 0,
    genres: overrides.genres ?? ['Action'],
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  };
}

beforeEach(() => {
  state.prefs = { quickWinMaxHours: 15, metricsDisabled: [] };
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
  invalidateLibrarySnapshot();
});

describe('buildMarqueeItems', () => {
  // Regression guard: a missing sabermetrics import (e.g. backlogOps) used to
  // throw a ReferenceError mid-build. backlogOps is only reached when the
  // snapshot has sabermetric data, so this exercises that path.
  it('builds without throwing when sabermetric data exists', () => {
    const games = [
      game({ status: 'finished', id: '1', playtime_minutes: 120, hltb_main_hours: 5 }),
      game({ status: 'backlog', id: '2' }),
    ];
    const snap = getLibrarySnapshot(games);
    let items;
    expect(() => { items = buildMarqueeItems(games, snap); }).not.toThrow();
    const labels = items.map((it) => it.label);
    // Normal-weight items are never sampled out, so these are deterministic.
    expect(labels).toContain('games owned');
    expect(labels).toContain('in backlog');
  });

  it('renderMarqueeHtml emits title tooltips for known metrics', () => {
    const games = [
      game({ status: 'finished', id: '1', playtime_minutes: 120, hltb_main_hours: 5 }),
      game({ status: 'backlog', id: '2' }),
    ];
    const snap = getLibrarySnapshot(games);
    const items = buildMarqueeItems(games, snap);
    const html = renderMarqueeHtml(items);
    const opsTip = marqueeTip('backlog OPS');
    if (items.some(it => it.label === 'backlog OPS')) {
      expect(html).toContain(`title="${opsTip.replace(/"/g, '&quot;')}"`);
    }
    expect(html).toContain('title="Total games in your merged library');
  });

  it('uses the passed snapshot without throwing on an empty library', () => {
    const snap = getLibrarySnapshot([]);
    expect(() => buildMarqueeItems([], snap)).not.toThrow();
  });

  it('excludes disabled catalog metrics from marquee output', () => {
    state.prefs.metricsDisabled = ['games owned', 'in backlog'];
    const games = [
      game({ status: 'finished', id: '1', playtime_minutes: 120, hltb_main_hours: 5 }),
      game({ status: 'backlog', id: '2' }),
    ];
    const snap = getLibrarySnapshot(games);
    const items = buildMarqueeItems(games, snap);
    const labels = items.map((it) => it.label);
    expect(labels).not.toContain('games owned');
    expect(labels).not.toContain('in backlog');
    expect(labels.length).toBeGreaterThan(0);
  });
});

describe('applyMarqueeSpeed', () => {
  it('sets --marquee-duration from measured track width', () => {
    document.documentElement.style.setProperty('--marquee-px-per-sec', String(MARQUEE_PX_PER_SEC));
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="dash-marquee">
        <div class="dash-marquee-track" style="width: 800px">a</div>
      </div>`;
    const track = root.querySelector('.dash-marquee-track');
    Object.defineProperty(track, 'scrollWidth', { value: 800, configurable: true });

    applyMarqueeSpeed(root);

    expect(track.style.getPropertyValue('--marquee-duration')).toBe(`${400 / MARQUEE_PX_PER_SEC}s`);
  });

  it('no-ops when track width is zero', () => {
    const root = document.createElement('div');
    root.innerHTML = `<div class="dash-marquee-track"></div>`;
    const track = root.querySelector('.dash-marquee-track');
    Object.defineProperty(track, 'scrollWidth', { value: 0, configurable: true });

    applyMarqueeSpeed(root);

    expect(track.style.getPropertyValue('--marquee-duration')).toBe('');
  });

  it('marks the marquee static when one copy does not fill the bar', () => {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="dash-marquee">
        <div class="dash-marquee-track"><span class="dash-marquee-copy">a</span><span class="dash-marquee-copy" aria-hidden="true">a</span></div>
      </div>`;
    const marquee = root.querySelector('.dash-marquee');
    const copy = root.querySelector('.dash-marquee-copy');
    Object.defineProperty(copy, 'scrollWidth', { value: 200, configurable: true });
    Object.defineProperty(marquee, 'clientWidth', { value: 800, configurable: true });

    applyMarqueeSpeed(root);

    expect(marquee.classList.contains('dash-marquee--static')).toBe(true);
    expect(root.querySelector('.dash-marquee-track').style.getPropertyValue('--marquee-duration')).toBe('');
  });

  it('animates (not static) when the chips overflow the bar', () => {
    document.documentElement.style.setProperty('--marquee-px-per-sec', String(MARQUEE_PX_PER_SEC));
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="dash-marquee">
        <div class="dash-marquee-track"><span class="dash-marquee-copy">a</span><span class="dash-marquee-copy" aria-hidden="true">a</span></div>
      </div>`;
    const marquee = root.querySelector('.dash-marquee');
    const copy = root.querySelector('.dash-marquee-copy');
    Object.defineProperty(copy, 'scrollWidth', { value: 1000, configurable: true });
    Object.defineProperty(marquee, 'clientWidth', { value: 800, configurable: true });

    applyMarqueeSpeed(root);

    expect(marquee.classList.contains('dash-marquee--static')).toBe(false);
    expect(root.querySelector('.dash-marquee-track').style.getPropertyValue('--marquee-duration')).toBe(`${1000 / MARQUEE_PX_PER_SEC}s`);
  });

  it('renderMarqueeHtml returns empty string for no items (no broken marquee)', () => {
    expect(renderMarqueeHtml([])).toBe('');
  });
});
