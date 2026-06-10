/**
 * Tests for js/personal-storage.js — notes writes, import merge, orphan
 * cleanup, and the one-shot legacy-tag stripper. Personal tags are gone;
 * stripLegacyTags is the single migration that drops them on first boot.
 */

import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { state } from '../js/state.js';
import {
  setPersonal,
  mergeImportedPersonal,
  getPersonal,
  canonicalizeNotesAcrossTitles,
  reconcileNotesAcrossTitles,
  findOrphanPersonalKeys,
  countOrphanPersonalKeys,
  prunePersonalKeys,
  stripLegacyTags,
  flushSavePersonal,
  savePersonal,
  saveManualGames,
} from '../js/personal-storage.js';
import { gameKey } from '../js/game-core.js';

const testGame = { store: 'steam', id: 42, appid: 42, name: 'Test Game' };
const hadesSteam = { store: 'steam', id: 1, appid: 1, name: 'Hades' };
const hadesEpic = { store: 'epic', id: 'hades-epic', epic_catalog_id: 'hades-epic', name: 'Hades' };

beforeEach(() => {
  state.personal = {};
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  state.prefs = {};
  window._dataVersion = 0;
});

describe('localStorage quota handling', () => {
  it('flushSavePersonal and saveManualGames swallow quota errors and warn', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      const err = new Error('quota');
      err.name = 'QuotaExceededError';
      throw err;
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      state.personal = { 'steam:1': { status: 'backlog' } };
      savePersonal();
      expect(() => flushSavePersonal()).not.toThrow();
      expect(() => saveManualGames([{ store: 'manual', id: 'x', name: 'X' }])).not.toThrow();
      expect(warn).toHaveBeenCalledTimes(2);
    } finally {
      setItemSpy.mockRestore();
      warn.mockRestore();
    }
  });
});

describe('setPersonal — notes', () => {
  it('writes notes without clobbering status', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'playing',
      notes: '',
      priority: 0,
      hltb_override: null,
    };
    setPersonal(testGame, 'notes', 'try on deck', { silent: true });
    expect(state.personal[key].notes).toBe('try on deck');
    expect(state.personal[key].status).toBe('playing');
    expect(window._dataVersion).toBe(1);
    expect(getPersonal(testGame).notes).toBe('try on deck');
  });
});

describe('mergeImportedPersonal', () => {
  it('preserves existing status when import only has notes', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'next',
      notes: 'old note',
      priority: 0,
      hltb_override: null,
    };
    mergeImportedPersonal({
      [key]: { notes: 'imported note' },
    });
    expect(state.personal[key].notes).toBe('imported note');
    expect(state.personal[key].status).toBe('next');
  });

  it('drops legacy tags fields silently on import', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'backlog',
      notes: '',
      priority: 0,
      hltb_override: null,
    };
    mergeImportedPersonal({
      [key]: { status: 'next', tags: ['cozy', 'co-op'] },
    });
    expect(state.personal[key].status).toBe('next');
    expect(state.personal[key]).not.toHaveProperty('tags');
  });
});

describe('canonical cross-store notes', () => {
  beforeEach(() => {
    state.allGames = [hadesSteam, hadesEpic];
  });

  it('setPersonal(notes) mirrors across same-title keys (last-write-wins)', () => {
    setPersonal(hadesSteam, 'notes', 'try on deck', { silent: true });
    expect(getPersonal(hadesSteam).notes).toBe('try on deck');
    expect(getPersonal(hadesEpic).notes).toBe('try on deck');
    setPersonal(hadesEpic, 'notes', 'epic note wins', { silent: true });
    expect(getPersonal(hadesSteam).notes).toBe('epic note wins');
    expect(getPersonal(hadesEpic).notes).toBe('epic note wins');
  });

  it('canonicalizeNotesAcrossTitles picks longest note per group', () => {
    state.personal['steam:1'] = { status: 'backlog', notes: 'short', priority: 0, hltb_override: null };
    state.personal['epic:hades-epic'] = { status: 'backlog', notes: 'much longer note text', priority: 0, hltb_override: null };
    delete state.personal.__notes_canonicalized_v1;
    expect(canonicalizeNotesAcrossTitles()).toBe(true);
    expect(getPersonal(hadesSteam).notes).toBe('much longer note text');
    expect(getPersonal(hadesEpic).notes).toBe('much longer note text');
    expect(canonicalizeNotesAcrossTitles()).toBe(false);
  });

  it('reconcileNotesAcrossTitles is idempotent when notes already match', () => {
    setPersonal(hadesSteam, 'notes', 'same', { silent: true });
    expect(reconcileNotesAcrossTitles()).toBe(false);
  });

  it('canonicalizeNotesAcrossTitles does not materialize empty personal rows', () => {
    state.allGames = [hadesSteam, hadesEpic, { store: 'steam', id: 99, name: 'Lonely Game' }];
    state.personal = {};
    delete state.personal.__notes_canonicalized_v1;
    canonicalizeNotesAcrossTitles();
    const keys = Object.keys(state.personal).filter(k => !k.startsWith('__'));
    expect(keys).toEqual([]);
  });
});

describe('orphan personal keys', () => {
  it('findOrphanPersonalKeys returns keys with no matching game', () => {
    state.allGames = [{ store: 'steam', id: 1, name: 'Hades' }];
    state.personal = {
      'steam:1': { status: 'next', notes: '' },
      'gog:gone': { status: 'finished', notes: '' },
      'epic:abandoned': { status: 'backlog', notes: 'still want' },
      __migrated_v3: true,
      __tags_removed_v1: true,
    };
    const orphans = findOrphanPersonalKeys();
    const keys = orphans.map(o => o.key).sort();
    expect(keys).toEqual(['epic:abandoned', 'gog:gone']);
  });

  it('orphan rows mark hasData=true when status/notes/hltb differ from defaults', () => {
    state.allGames = [];
    state.personal = {
      'gog:empty': { status: 'backlog', notes: '', hltb_override: null },
      'gog:withNote': { status: 'backlog', notes: 'finish' },
      'gog:withStatus': { status: 'finished', notes: '' },
      'gog:withHltb': { status: 'backlog', notes: '', hltb_override: 5 },
    };
    const byKey = Object.fromEntries(findOrphanPersonalKeys().map(o => [o.key, o]));
    expect(byKey['gog:empty'].hasData).toBe(false);
    expect(byKey['gog:withNote'].hasData).toBe(true);
    expect(byKey['gog:withStatus'].hasData).toBe(true);
    expect(byKey['gog:withHltb'].hasData).toBe(true);
  });

  it('countOrphanPersonalKeys ignores meta keys', () => {
    state.allGames = [{ store: 'steam', id: 1, name: 'Hades' }];
    state.personal = {
      'steam:1': { status: 'next', notes: '' },
      'gog:gone': { status: 'backlog', notes: '' },
      __migrated_v3: true,
      __tags_removed_v1: true,
    };
    expect(countOrphanPersonalKeys()).toBe(1);
  });

  it('prunePersonalKeys removes selected keys and bumps _dataVersion', () => {
    state.allGames = [];
    state.personal = {
      'gog:a': { status: 'backlog', notes: '' },
      'gog:b': { status: 'next', notes: '' },
    };
    window._dataVersion = 5;
    const removed = prunePersonalKeys(['gog:a']);
    expect(removed).toBe(1);
    expect(state.personal).not.toHaveProperty('gog:a');
    expect(state.personal).toHaveProperty('gog:b');
    expect(window._dataVersion).toBe(6);
  });

  it('prunePersonalKeys refuses to remove meta keys', () => {
    state.personal = { __migrated_v3: true, 'gog:a': { status: 'backlog' } };
    prunePersonalKeys(['__migrated_v3']);
    expect(state.personal.__migrated_v3).toBe(true);
  });
});

describe('stripLegacyTags', () => {
  it('drops the tags field from every record and stamps the migration flag', () => {
    state.personal = {
      'steam:1': { status: 'backlog', notes: '', tags: ['cozy', 'short'] },
      'gog:7':   { status: 'next',    notes: 'note', tags: [] },
      __migrated_v3: true,
    };
    state.prefs = { tagFilters: ['cozy'], tagFilterMode: 'AND', storeFilter: '' };
    expect(stripLegacyTags()).toBe(true);
    expect(state.personal['steam:1']).not.toHaveProperty('tags');
    expect(state.personal['gog:7']).not.toHaveProperty('tags');
    expect(state.personal.__tags_removed_v1).toBe(true);
    expect(state.prefs.tagFilters).toBeUndefined();
    expect(state.prefs.tagFilterMode).toBeUndefined();
    expect(state.prefs.storeFilter).toBe('');
  });

  it('is idempotent — second call is a no-op', () => {
    state.personal = {
      'steam:1': { status: 'backlog', notes: '', tags: ['cozy'] },
    };
    stripLegacyTags();
    expect(stripLegacyTags()).toBe(false);
  });
});
