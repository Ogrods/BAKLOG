/**
 * Tests for js/personal-storage.js — notes writes and import merge.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  setPersonal,
  mergeImportedPersonal,
  getPersonal,
  normalizeTag,
  addTagToGame,
  removeTagFromGame,
  renameTagGlobally,
  mergeTagGlobally,
  deleteTagGlobally,
  allPersonalTags,
  canonicalizeTagsAcrossTitles,
  canonicalizeNotesAcrossTitles,
  reconcileNotesAcrossTitles,
  findOrphanPersonalKeys,
  countOrphanPersonalKeys,
  prunePersonalKeys,
} from '../js/personal-storage.js';
import { gameKey, getSameTitleKeys } from '../js/game-core.js';

const testGame = { store: 'steam', id: 42, appid: 42, name: 'Test Game' };
const hadesSteam = { store: 'steam', id: 1, appid: 1, name: 'Hades' };
const hadesEpic = { store: 'epic', id: 'hades-epic', epic_catalog_id: 'hades-epic', name: 'Hades' };

beforeEach(() => {
  state.personal = {};
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  state.prefs = { tagFilters: [], tagFilterMode: 'OR' };
  window._dataVersion = 0;
});

describe('setPersonal — notes', () => {
  it('writes notes without clobbering status or tags', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'playing',
      notes: '',
      priority: 0,
      hltb_override: null,
      tags: ['cozy'],
    };
    setPersonal(testGame, 'notes', 'try on deck', { silent: true });
    expect(state.personal[key].notes).toBe('try on deck');
    expect(state.personal[key].status).toBe('playing');
    expect(state.personal[key].tags).toEqual(['cozy']);
    expect(window._dataVersion).toBe(1);
    expect(getPersonal(testGame).notes).toBe('try on deck');
  });
});

describe('mergeImportedPersonal', () => {
  it('preserves existing status and tags when import only has notes', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'next',
      notes: 'old note',
      priority: 0,
      hltb_override: null,
      tags: ['backlog'],
    };
    mergeImportedPersonal({
      [key]: { notes: 'imported note' },
    });
    expect(state.personal[key].notes).toBe('imported note');
    expect(state.personal[key].status).toBe('next');
    expect(state.personal[key].tags).toEqual(['backlog']);
  });

  it('unions tags instead of replacing', () => {
    const key = gameKey(testGame);
    state.personal[key] = {
      status: 'backlog',
      notes: '',
      priority: 0,
      hltb_override: null,
      tags: ['co-op'],
    };
    mergeImportedPersonal({
      [key]: { tags: ['cozy', 'co-op'] },
    });
    expect(state.personal[key].tags.sort()).toEqual(['co-op', 'cozy']);
  });
});

describe('normalizeTag', () => {
  it('lowercases, trims, collapses spaces, caps at 32 chars', () => {
    expect(normalizeTag('  Co-Op  ')).toBe('co-op');
    expect(normalizeTag('A'.repeat(40)).length).toBe(32);
    expect(normalizeTag('')).toBe('');
  });
});

describe('canonical cross-store tags', () => {
  beforeEach(() => {
    state.allGames = [hadesSteam, hadesEpic];
  });

  it('getSameTitleKeys returns every store copy', () => {
    const keys = getSameTitleKeys(hadesSteam).sort();
    expect(keys).toEqual(['epic:hades-epic', 'steam:1'].sort());
  });

  it('addTagToGame mirrors across same-title keys', () => {
    addTagToGame(hadesSteam, 'cozy');
    expect(getPersonal(hadesSteam).tags).toEqual(['cozy']);
    expect(getPersonal(hadesEpic).tags).toEqual(['cozy']);
  });

  it('removeTagFromGame mirrors across same-title keys', () => {
    addTagToGame(hadesSteam, 'cozy');
    removeTagFromGame(hadesEpic, 'cozy');
    expect(getPersonal(hadesSteam).tags).toEqual([]);
    expect(getPersonal(hadesEpic).tags).toEqual([]);
  });

  it('allPersonalTags counts one game per title group', () => {
    addTagToGame(hadesSteam, 'cozy');
    expect(allPersonalTags()).toEqual([['cozy', 1]]);
  });

  it('canonicalizeTagsAcrossTitles unions tags and is idempotent', () => {
    state.personal['steam:1'] = { status: 'backlog', notes: '', priority: 0, hltb_override: null, tags: ['cozy'] };
    state.personal['epic:hades-epic'] = { status: 'backlog', notes: '', priority: 0, hltb_override: null, tags: ['co-op'] };
    delete state.personal.__tags_canonicalized_v1;
    expect(canonicalizeTagsAcrossTitles()).toBe(true);
    expect(getPersonal(hadesSteam).tags.sort()).toEqual(['co-op', 'cozy']);
    expect(getPersonal(hadesEpic).tags.sort()).toEqual(['co-op', 'cozy']);
    expect(canonicalizeTagsAcrossTitles()).toBe(false);
  });
});

describe('global tag management', () => {
  beforeEach(() => {
    state.allGames = [testGame];
    addTagToGame(testGame, 'cozy');
  });

  it('renameTagGlobally updates every key and prefs filter', () => {
    state.prefs.tagFilters = ['cozy'];
    renameTagGlobally('cozy', 'cosy');
    expect(getPersonal(testGame).tags).toEqual(['cosy']);
    expect(state.prefs.tagFilters).toEqual(['cosy']);
  });

  it('mergeTagGlobally collapses duplicate tags on a key', () => {
    addTagToGame(testGame, 'co-op');
    mergeTagGlobally('co-op', 'cozy');
    expect(getPersonal(testGame).tags).toEqual(['cozy']);
  });

  it('deleteTagGlobally removes tag everywhere and clears filter', () => {
    state.prefs.tagFilters = ['cozy'];
    deleteTagGlobally('cozy');
    expect(getPersonal(testGame).tags).toEqual([]);
    expect(state.prefs.tagFilters).toEqual([]);
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
    state.personal['steam:1'] = { status: 'backlog', notes: 'short', tags: [], priority: 0, hltb_override: null };
    state.personal['epic:hades-epic'] = { status: 'backlog', notes: 'much longer note text', tags: [], priority: 0, hltb_override: null };
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
});

describe('orphan personal keys', () => {
  it('findOrphanPersonalKeys returns keys with no matching game', () => {
    state.allGames = [{ store: 'steam', id: 1, name: 'Hades' }];
    state.personal = {
      'steam:1': { status: 'next', notes: '', tags: [] },
      'gog:gone': { status: 'finished', notes: '', tags: [] },
      'epic:abandoned': { status: 'backlog', notes: 'still want', tags: ['cozy'] },
      __migrated_v3: true,
      __tags_canonicalized_v1: true,
    };
    const orphans = findOrphanPersonalKeys();
    const keys = orphans.map(o => o.key).sort();
    expect(keys).toEqual(['epic:abandoned', 'gog:gone']);
  });

  it('orphan rows mark hasData=true when status/notes/tags/hltb differ from defaults', () => {
    state.allGames = [];
    state.personal = {
      'gog:empty': { status: 'backlog', notes: '', tags: [], hltb_override: null },
      'gog:withNote': { status: 'backlog', notes: 'finish', tags: [] },
      'gog:withTag': { status: 'backlog', notes: '', tags: ['short'] },
      'gog:withStatus': { status: 'finished', notes: '', tags: [] },
      'gog:withHltb': { status: 'backlog', notes: '', tags: [], hltb_override: 5 },
    };
    const byKey = Object.fromEntries(findOrphanPersonalKeys().map(o => [o.key, o]));
    expect(byKey['gog:empty'].hasData).toBe(false);
    expect(byKey['gog:withNote'].hasData).toBe(true);
    expect(byKey['gog:withTag'].hasData).toBe(true);
    expect(byKey['gog:withStatus'].hasData).toBe(true);
    expect(byKey['gog:withHltb'].hasData).toBe(true);
  });

  it('countOrphanPersonalKeys ignores meta keys', () => {
    state.allGames = [{ store: 'steam', id: 1, name: 'Hades' }];
    state.personal = {
      'steam:1': { status: 'next', notes: '', tags: [] },
      'gog:gone': { status: 'backlog', notes: '', tags: [] },
      __migrated_v3: true,
      __tags_canonicalized_v1: true,
    };
    expect(countOrphanPersonalKeys()).toBe(1);
  });

  it('prunePersonalKeys removes selected keys and bumps _dataVersion', () => {
    state.allGames = [];
    state.personal = {
      'gog:a': { status: 'backlog', notes: '', tags: [] },
      'gog:b': { status: 'next', notes: '', tags: [] },
    };
    window._dataVersion = 5;
    const removed = prunePersonalKeys(['gog:a']);
    expect(removed).toBe(1);
    expect(state.personal).not.toHaveProperty('gog:a');
    expect(state.personal).toHaveProperty('gog:b');
    expect(window._dataVersion).toBe(6);
  });

  it('prunePersonalKeys refuses to remove meta keys', () => {
    state.personal = { __migrated_v3: true, 'gog:a': { status: 'backlog', tags: [] } };
    prunePersonalKeys(['__migrated_v3']);
    expect(state.personal.__migrated_v3).toBe(true);
  });
});
