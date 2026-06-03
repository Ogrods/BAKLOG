import { describe, it, expect, beforeEach } from 'vitest';
import {
  ACTIVE_PROFILE_LS,
  prefsStorageKey,
  itadSnapshotStorageKey,
  activeProfileId,
} from '../js/profiles.js';
import { PREFS_KEY } from '../js/state.js';

describe('profiles storage keys', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults to default profile id with bare storage keys', () => {
    expect(activeProfileId()).toBe('default');
    expect(prefsStorageKey()).toBe(PREFS_KEY);
    expect(itadSnapshotStorageKey()).toBe('baklog-itad-snapshot');
  });

  it('suffixes keys by active profile from localStorage', () => {
    localStorage.setItem(ACTIVE_PROFILE_LS, 'work');
    expect(prefsStorageKey()).toBe(`${PREFS_KEY}:work`);
    expect(itadSnapshotStorageKey()).toBe('baklog-itad-snapshot:work');
  });
});
