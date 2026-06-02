import { describe, expect, it } from 'vitest';
import { passesTagFilterFromPrefs } from '../js/tag-filter.js';

describe('passesTagFilterFromPrefs', () => {
  it('passes when no tag filters active', () => {
    expect(passesTagFilterFromPrefs({}, ['cozy'])).toBe(true);
    expect(passesTagFilterFromPrefs({ tagFilters: [] }, [])).toBe(true);
  });

  it('OR mode — any filter tag matches', () => {
    const prefs = { tagFilters: ['cozy', 'co-op'], tagFilterMode: 'OR' };
    expect(passesTagFilterFromPrefs(prefs, ['co-op'])).toBe(true);
    expect(passesTagFilterFromPrefs(prefs, ['other'])).toBe(false);
  });

  it('AND mode — every filter tag required', () => {
    const prefs = { tagFilters: ['cozy', 'short'], tagFilterMode: 'AND' };
    expect(passesTagFilterFromPrefs(prefs, ['cozy', 'short'])).toBe(true);
    expect(passesTagFilterFromPrefs(prefs, ['cozy'])).toBe(false);
  });
});
