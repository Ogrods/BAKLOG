/**
 * Tests for js/game-core.js — normalization, dedup scoring, identity helpers.
 *
 * Scope chosen per find_no_js_tests: normalizeNameForDedup + scoreEntry are the
 * inputs to recomputeCrossStoreHidden, which decides which rows the user sees.
 * A regression here means a duplicate row appears (or a legit game disappears).
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  normalizeNameForDedup,
  scoreEntry,
  storePriority,
  isJunkEntry,
  dedupeWithinStore,
  normalizeGame,
  gameKey,
  getSameTitleKeys,
  alphaBucket,
  formatHours,
  formatReleaseDate,
  recomputeCrossStoreHidden,
  combinedPlaytime,
  combinedPlaytimeTooltip,
  storeUrlForGame,
  trophyProgressPillHtml,
  platinumBadgeHtml,
} from '../js/game-core.js';
import { state } from '../js/state.js';

describe('normalizeNameForDedup', () => {
  it('lowercases and strips punctuation', () => {
    expect(normalizeNameForDedup('Cyberpunk 2077')).toBe('cyberpunk 2077');
    expect(normalizeNameForDedup('Half-Life: Alyx')).toBe('half life alyx');
  });

  it('strips trademark / registered / copyright glyphs', () => {
    expect(normalizeNameForDedup('Tomb Raider™')).toBe('tomb raider');
    expect(normalizeNameForDedup('Doom®')).toBe('doom');
  });

  it('drops common edition/version tokens so re-releases dedup correctly', () => {
    expect(normalizeNameForDedup('Skyrim Special Edition'))
      .toBe(normalizeNameForDedup('Skyrim'));
    expect(normalizeNameForDedup('Dark Souls: Remastered'))
      .toBe(normalizeNameForDedup('Dark Souls'));
    expect(normalizeNameForDedup('The Witcher 3: Game of the Year'))
      .toBe(normalizeNameForDedup('Witcher 3'));
  });

  it('collapses whitespace', () => {
    expect(normalizeNameForDedup('  Spaced   Out  ')).toBe('spaced out');
  });

  it('returns "" for missing / nullish input', () => {
    expect(normalizeNameForDedup(null)).toBe('');
    expect(normalizeNameForDedup(undefined)).toBe('');
    expect(normalizeNameForDedup('')).toBe('');
  });
});

describe('scoreEntry', () => {
  it('rewards more populated metadata', () => {
    const empty = {};
    const full = {
      header_image: 'x',
      library_image: 'x',
      hltb_main_hours: 10,
      steam_review_percent: 80,
      release_date: '2020-01-01',
      genres: ['Action'],
      playtime_minutes: 30,
    };
    expect(scoreEntry(full)).toBeGreaterThan(scoreEntry(empty));
  });

  it('header_image is the highest single-field signal', () => {
    expect(scoreEntry({ header_image: 'x' })).toBeGreaterThan(
      scoreEntry({ release_date: '2020-01-01' }),
    );
  });
});

describe('storePriority', () => {
  it('orders steam highest, manual lowest, unknown lowest+1', () => {
    expect(storePriority('steam')).toBeLessThan(storePriority('gog'));
    expect(storePriority('gog')).toBeLessThan(storePriority('manual'));
    expect(storePriority('nonexistent-store')).toBeGreaterThanOrEqual(storePriority('manual'));
  });
});

describe('isJunkEntry', () => {
  it('flags blank names', () => {
    expect(isJunkEntry({ name: '' })).toBe(true);
    expect(isJunkEntry({ name: '   ' })).toBe(true);
  });

  it('flags explicit junk names from JUNK_NAMES', () => {
    expect(isJunkEntry({ name: 'live' })).toBe(true);
    expect(isJunkEntry({ name: 'HBO Max' })).toBe(true);
  });

  it('lets real games through', () => {
    expect(isJunkEntry({ name: 'Hades' })).toBe(false);
    expect(isJunkEntry({ name: 'Hollow Knight' })).toBe(false);
    expect(isJunkEntry({ name: 'Fortnite' })).toBe(false);
  });

  it('flags cosmetic wallpaper SKUs but not Wallpaper Engine', () => {
    expect(isJunkEntry({ name: 'HD Wallpaper' })).toBe(true);
    expect(isJunkEntry({ name: 'Death Stranding — HD Wallpaper' })).toBe(true);
    expect(isJunkEntry({ name: 'Wallpaper Engine' })).toBe(false);
  });

  it('flags Epic entitlement slugs but not real underscored titles', () => {
    expect(isJunkEntry({ name: 'Fortnite_StWContent' })).toBe(true);
    expect(isJunkEntry({ name: 'Fortnite_Studio' })).toBe(true);
    expect(isJunkEntry({ name: "Aerial_Knight's Never Yield" })).toBe(false);
  });
});

describe('dedupeWithinStore', () => {
  it('keeps the higher-scored duplicate when ids collide', () => {
    const games = [
      { store: 'steam', id: 1, name: 'Hades' },
      { store: 'steam', id: 1, name: 'Hades', header_image: 'better' },
    ];
    const out = dedupeWithinStore(games);
    expect(out).toHaveLength(1);
    expect(out[0].header_image).toBe('better');
  });

  it('dedups by store+normalized-name as well as id', () => {
    const games = [
      { store: 'steam', id: 1, name: 'Skyrim' },
      { store: 'steam', id: 2, name: 'Skyrim Special Edition', header_image: 'x' },
    ];
    const out = dedupeWithinStore(games);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(2);
  });

  it('drops junk entries entirely', () => {
    const games = [
      { store: 'steam', id: 1, name: 'live' },
      { store: 'steam', id: 2, name: 'Hades' },
    ];
    const out = dedupeWithinStore(games);
    expect(out.map(g => g.name)).toEqual(['Hades']);
  });
});

describe('normalizeGame', () => {
  it('passes through when store + id already set', () => {
    const g = { store: 'steam', id: 1, name: 'X' };
    expect(normalizeGame(g)).toBe(g);
  });

  it('falls back to appid for Steam', () => {
    const g = { appid: 730, name: 'CS' };
    const out = normalizeGame(g);
    expect(out.store).toBe('steam');
    expect(out.id).toBe(730);
  });

  it('picks the right id field per store', () => {
    expect(normalizeGame({ store: 'gog', gog_id: 'g1', name: 'X' }).id).toBe('g1');
    expect(normalizeGame({ store: 'psn', psn_id: 'C1', name: 'X' }).id).toBe('C1');
    expect(normalizeGame({ store: 'epic', epic_catalog_id: 'e1', name: 'X' }).id).toBe('e1');
    expect(normalizeGame({ store: 'ea', ea_id: 'ea-42', name: 'X' }).id).toBe('ea-42');
  });
});

describe('gameKey', () => {
  it('matches store:id', () => {
    expect(gameKey({ store: 'gog', id: 1 })).toBe('gog:1');
  });

  it('falls back through alternative id fields', () => {
    expect(gameKey({ appid: 1 })).toBe('steam:1');
  });

  it('uses ea_id when that is the only identifier (matches normalizeGame + worker)', () => {
    expect(gameKey({ store: 'ea', ea_id: 'ea-42', name: 'FIFA' })).toBe('ea:ea-42');
  });
});

describe('recomputeCrossStoreHidden — hidden keys', () => {
  let savedAllGames;
  let savedHidden;
  let savedDedup;

  beforeEach(() => {
    savedAllGames = state.allGames;
    savedHidden = state.crossStoreHiddenKeys;
    savedDedup = state.sessionPrefs.crossStoreDedup;
    state.sessionPrefs.crossStoreDedup = true;
  });

  afterEach(() => {
    state.allGames = savedAllGames;
    state.crossStoreHiddenKeys = savedHidden;
    state.sessionPrefs.crossStoreDedup = savedDedup;
  });

  it('hides lower-priority store copies; steam wins over psn and gog', () => {
    state.allGames = [
      { store: 'psn', id: 'NPWR1', name: 'Death Stranding' },
      { store: 'steam', id: 1, appid: 1, name: 'Death Stranding' },
      { store: 'gog', id: 'gog-1', name: 'Death Stranding' },
    ];
    recomputeCrossStoreHidden();
    expect(state.crossStoreHiddenKeys.has('steam:1')).toBe(false);
    expect(state.crossStoreHiddenKeys.has('psn:NPWR1')).toBe(true);
    expect(state.crossStoreHiddenKeys.has('gog:gog-1')).toBe(true);
  });

  it('keeps the higher scoreEntry sibling when store priority ties', () => {
    state.allGames = [
      { store: 'gog', id: 'a', name: 'Indie Title', release_date: '2020-01-01' },
      { store: 'gog', id: 'b', name: 'Indie Title', header_image: 'https://x' },
    ];
    recomputeCrossStoreHidden();
    expect(state.crossStoreHiddenKeys.has('gog:b')).toBe(false);
    expect(state.crossStoreHiddenKeys.has('gog:a')).toBe(true);
  });

  it('does not hide siblings when crossStoreDedup is off', () => {
    state.sessionPrefs.crossStoreDedup = false;
    state.allGames = [
      { store: 'steam', id: 1, appid: 1, name: 'Doom' },
      { store: 'psn', id: 'NPWR9', name: 'Doom' },
    ];
    recomputeCrossStoreHidden();
    expect(state.crossStoreHiddenKeys.size).toBe(0);
  });
});

describe('combinedPlaytime (cross-store)', () => {
  let savedAllGames;
  let savedHidden;
  let savedOwned;
  let savedPlaytime;
  let savedWishlist;
  let savedWishlistGames;
  let savedDedup;

  beforeEach(() => {
    savedAllGames = state.allGames;
    savedHidden = state.crossStoreHiddenKeys;
    savedOwned = state.crossStoreOwnedStores;
    savedPlaytime = state.crossStorePlaytimeByKey;
    savedWishlist = state.wishlistCrossStoreHiddenKeys;
    savedWishlistGames = state.wishlistGames;
    savedDedup = state.sessionPrefs.crossStoreDedup;
    state.wishlistGames = [];
    state.sessionPrefs.crossStoreDedup = true;
  });

  afterEach(() => {
    state.allGames = savedAllGames;
    state.crossStoreHiddenKeys = savedHidden;
    state.crossStoreOwnedStores = savedOwned;
    state.crossStorePlaytimeByKey = savedPlaytime;
    state.wishlistCrossStoreHiddenKeys = savedWishlist;
    state.wishlistGames = savedWishlistGames;
    state.sessionPrefs.crossStoreDedup = savedDedup;
  });

  it('sums playtime across stores when dedup is on', () => {
    state.allGames = [
      { store: 'steam', id: 1, name: 'Death Stranding', playtime_minutes: 120 },
      { store: 'psn', id: 'NPWR1', name: 'Death Stranding', playtime_minutes: 2780 },
    ];
    recomputeCrossStoreHidden();
    expect(combinedPlaytime(state.allGames[0])).toBe(2900);
    expect(combinedPlaytime(state.allGames[1])).toBe(2780);
  });

  it('returns raw playtime when dedup is off', () => {
    state.sessionPrefs.crossStoreDedup = false;
    state.allGames = [
      { store: 'steam', id: 1, name: 'Death Stranding', playtime_minutes: 120 },
      { store: 'psn', id: 'NPWR1', name: 'Death Stranding', playtime_minutes: 2780 },
    ];
    recomputeCrossStoreHidden();
    expect(state.crossStorePlaytimeByKey.size).toBe(0);
    expect(combinedPlaytime(state.allGames[0])).toBe(120);
  });

  it('skips groups where every store has 0 minutes', () => {
    state.allGames = [
      { store: 'steam', id: 2, name: 'Untouched', playtime_minutes: 0 },
      { store: 'psn', id: 'NPWR2', name: 'Untouched', playtime_minutes: 0 },
    ];
    recomputeCrossStoreHidden();
    expect(state.crossStorePlaytimeByKey.size).toBe(0);
    expect(combinedPlaytime(state.allGames[0])).toBe(0);
  });

  it('produces a per-store tooltip only when 2+ stores have playtime', () => {
    state.allGames = [
      { store: 'steam', id: 3, name: 'Doom', playtime_minutes: 600 },
      { store: 'psn', id: 'NPWR3', name: 'Doom', playtime_minutes: 60 },
    ];
    recomputeCrossStoreHidden();
    const rep = state.allGames[0];
    const tip = combinedPlaytimeTooltip(rep);
    expect(tip).toContain('STEAM: 10.0h');
    expect(tip).toContain('PSN: 1.0h');
  });

  it('returns empty tooltip when only one sibling has playtime', () => {
    state.allGames = [
      { store: 'steam', id: 4, name: 'Solo', playtime_minutes: 300 },
      { store: 'psn', id: 'NPWR4', name: 'Solo', playtime_minutes: 0 },
    ];
    recomputeCrossStoreHidden();
    const rep = state.allGames[0];
    expect(combinedPlaytimeTooltip(rep)).toBe('');
    expect(combinedPlaytime(rep)).toBe(300);
  });

  it('coerces NaN / negative playtime to 0', () => {
    state.allGames = [
      { store: 'steam', id: 5, name: 'Wobble', playtime_minutes: 'oops' },
      { store: 'psn', id: 'NPWR5', name: 'Wobble', playtime_minutes: -50 },
      { store: 'gog', id: 9, name: 'Wobble', playtime_minutes: 90 },
    ];
    recomputeCrossStoreHidden();
    expect(combinedPlaytime(state.allGames[0])).toBe(90);
  });
});

describe('storeUrlForGame — PSN', () => {
  it('uses concept_id even when store_url points to psnprofiles', () => {
    const g = {
      store: 'psn',
      id: 'NPWR22859_00',
      name: 'Ghost of Tsushima',
      concept_id: '235227',
      store_url: 'https://psnprofiles.com/trophies/NPWR22859_00',
    };
    expect(storeUrlForGame(g)).toBe('https://store.playstation.com/en-us/concept/235227');
  });

  it('falls back to PSN store search when no concept_id', () => {
    const g = {
      store: 'psn',
      id: 'NPWR16225_00',
      name: 'DEATH STRANDING',
      concept_id: null,
      store_url: 'https://psnprofiles.com/trophies/NPWR16225_00',
    };
    const out = storeUrlForGame(g);
    expect(out).toContain('store.playstation.com/en-us/search/');
    expect(out).toContain('DEATH%20STRANDING');
    expect(out).not.toContain('psnprofiles');
  });
});

describe('storeUrlForGame — Amazon', () => {
  it('uses Steam store search when steam_review_percent is set', () => {
    const g = {
      store: 'amazon',
      id: 'amzn-1',
      name: 'Hades',
      steam_review_percent: 98,
      store_url: 'https://www.amazon.com/dp/B08XXXX',
      asin: 'B08XXXX',
    };
    const out = storeUrlForGame(g);
    expect(out).toContain('store.steampowered.com/search/');
    expect(out).toContain(encodeURIComponent('Hades'));
    expect(out).not.toContain('amazon.com/dp/');
  });

  it('ignores cached retail /dp/ store_url when no Steam match', () => {
    const g = {
      store: 'amazon',
      id: 'amzn-2',
      name: 'Obscure Prime Game',
      store_url: 'https://www.amazon.com/dp/B0XXXX',
      asin: 'B0XXXX',
    };
    expect(storeUrlForGame(g)).toBe('https://luna.amazon.com/');
  });

  it('falls back to Luna when no steam_review_percent and no store_url', () => {
    const g = {
      store: 'amazon',
      id: 'amzn-3',
      name: 'Prime Only Title',
    };
    expect(storeUrlForGame(g)).toBe('https://luna.amazon.com/');
  });

  it('falls back to Luna when steam_review_percent set but name missing', () => {
    const g = {
      store: 'amazon',
      id: 'amzn-4',
      steam_review_percent: 85,
      name: '',
    };
    expect(storeUrlForGame(g)).toBe('https://luna.amazon.com/');
  });
});

describe('alphaBucket', () => {
  it('uppercases the first letter', () => {
    expect(alphaBucket('hades')).toBe('H');
  });

  it('returns # for digits and symbols', () => {
    expect(alphaBucket('7 Days to Die')).toBe('#');
    expect(alphaBucket('!Hello')).toBe('#');
  });

  it('returns # for empty input', () => {
    expect(alphaBucket('')).toBe('#');
    expect(alphaBucket(null)).toBe('#');
  });
});

describe('formatHours', () => {
  it('renders minutes as hours with 1 decimal', () => {
    expect(formatHours(60)).toBe('1.0h');
    expect(formatHours(90)).toBe('1.5h');
    expect(formatHours(3000)).toBe('50.0h');
  });

  it('returns 0h for missing playtime', () => {
    expect(formatHours(0)).toBe('0h');
    expect(formatHours(null)).toBe('0h');
    expect(formatHours(undefined)).toBe('0h');
  });
});

describe('getSameTitleKeys', () => {
  it('groups Steam, Epic, and GOG copies of the same title', () => {
    state.allGames = [
      { store: 'steam', id: 1, name: 'Hades' },
      { store: 'epic', id: 'e1', name: 'Hades' },
      { store: 'gog', id: 'g1', name: 'Hades' },
      { store: 'steam', id: 2, name: 'Zelda' },
    ];
    state.wishlistGames = [];
    state.itchGames = [];
    const keys = getSameTitleKeys({ store: 'steam', id: 1, name: 'Hades' }).sort();
    expect(keys).toEqual(['epic:e1', 'gog:g1', 'steam:1'].sort());
  });
});

describe('formatReleaseDate', () => {
  it('returns placeholder for empty', () => {
    expect(formatReleaseDate('')).toBe(' - ');
    expect(formatReleaseDate(null)).toBe(' - ');
  });

  it('parses year-only strings as-is', () => {
    expect(formatReleaseDate('2020')).toMatch(/2020/);
  });
});

describe('trophyProgressPillHtml', () => {
  it('returns empty when trophy_progress is absent', () => {
    expect(trophyProgressPillHtml(null)).toBe('');
    expect(trophyProgressPillHtml({ store: 'steam', id: 1 })).toBe('');
    expect(trophyProgressPillHtml({ store: 'psn', id: 'abc', trophy_progress: null })).toBe('');
  });

  it('renders an interactive button pill with rounded percent when trophy_progress is set', () => {
    const html = trophyProgressPillHtml({ store: 'psn', id: 'abc', trophy_progress: 73.4 });
    expect(html).toContain('trophy-pill');
    expect(html).toContain('data-trophy-pop');
    expect(html).toMatch(/<button[^>]*class="trophy-pill"/);
    expect(html).toContain('73%');
    expect(html).toContain('PSN trophy completion: 73%');
    expect(html).toContain('aria-haspopup="true"');
    expect(html).toContain('aria-expanded="false"');
  });

  it('labels the tooltip per store', () => {
    expect(trophyProgressPillHtml({ store: 'xbox', id: '1', trophy_progress: 50 }))
      .toContain('Xbox achievement completion: 50%');
    expect(trophyProgressPillHtml({ store: 'gog', id: '1', trophy_progress: 20 }))
      .toContain('Completion: 20%');
  });

  it('emits Xbox gamerscore data attributes when present', () => {
    const html = trophyProgressPillHtml({
      store: 'xbox',
      id: '1',
      trophy_progress: 42,
      xbox_gamerscore_current: 500,
      xbox_gamerscore_total: 1000,
    });
    expect(html).toContain('data-gs-cur="500"');
    expect(html).toContain('data-gs-total="1000"');
  });

  it('emits PSN trophy count data attributes when present', () => {
    const html = trophyProgressPillHtml({
      store: 'psn',
      id: 'abc',
      trophy_progress: 73,
      psn_trophies_earned: 12,
      psn_trophies_total: 33,
    });
    expect(html).toContain('data-tro-cur="12"');
    expect(html).toContain('data-tro-total="33"');
  });
});

describe('platinumBadgeHtml', () => {
  it('returns empty when platinum is not earned', () => {
    expect(platinumBadgeHtml(null)).toBe('');
    expect(platinumBadgeHtml({ store: 'psn', id: 'abc' })).toBe('');
    expect(platinumBadgeHtml({ store: 'psn', id: 'abc', psn_platinum_earned: false })).toBe('');
  });

  it('renders a platinum badge when earned', () => {
    const html = platinumBadgeHtml({ store: 'psn', id: 'abc', psn_platinum_earned: true });
    expect(html).toContain('plat-badge');
    expect(html).toContain('PLAT');
    expect(html).toContain('Platinum trophy earned');
  });
});
