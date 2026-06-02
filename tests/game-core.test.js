/**
 * Tests for js/game-core.js — normalization, dedup scoring, identity helpers.
 *
 * Scope chosen per find_no_js_tests: normalizeNameForDedup + scoreEntry are the
 * inputs to recomputeCrossStoreHidden, which decides which rows the user sees.
 * A regression here means a duplicate row appears (or a legit game disappears).
 */

import { describe, expect, it } from 'vitest';
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
    expect(isJunkEntry({ name: 'Fortnite' })).toBe(true);
  });

  it('lets real games through', () => {
    expect(isJunkEntry({ name: 'Hades' })).toBe(false);
    expect(isJunkEntry({ name: 'Hollow Knight' })).toBe(false);
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
  });
});

describe('gameKey', () => {
  it('matches store:id', () => {
    expect(gameKey({ store: 'gog', id: 1 })).toBe('gog:1');
  });

  it('falls back through alternative id fields', () => {
    expect(gameKey({ appid: 1 })).toBe('steam:1');
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
  it('returns — for empty', () => {
    expect(formatReleaseDate('')).toBe('—');
    expect(formatReleaseDate(null)).toBe('—');
  });

  it('parses year-only strings as-is', () => {
    expect(formatReleaseDate('2020')).toMatch(/2020/);
  });
});
