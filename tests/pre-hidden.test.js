import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { PRE_HIDDEN_KEYS } from '../js/hidden-defaults.js';
import { seedPreHiddenDefaults } from '../js/personal-storage.js';

beforeEach(() => {
  state.personal = {};
  window._dataVersion = 0;
});

describe('seedPreHiddenDefaults', () => {
  it('seeds all pre-hidden keys on first run', () => {
    seedPreHiddenDefaults();
    expect(state.personal.__pre_hidden_v1_seeded).toBe(true);
    for (const { key } of PRE_HIDDEN_KEYS) {
      expect(state.personal[key]?.hidden).toBe(true);
    }
  });

  it('is idempotent when meta flag is set', () => {
    seedPreHiddenDefaults();
    delete state.personal[PRE_HIDDEN_KEYS[0].key];
    seedPreHiddenDefaults();
    expect(state.personal[PRE_HIDDEN_KEYS[0].key]).toBeUndefined();
  });

  it('does not overwrite existing personal entries', () => {
    const key = PRE_HIDDEN_KEYS[0].key;
    state.personal[key] = { status: 'playing', notes: 'keep', priority: 0, hltb_override: null, hidden: false };
    seedPreHiddenDefaults();
    expect(state.personal[key].status).toBe('playing');
    expect(state.personal[key].hidden).toBe(false);
  });
});
