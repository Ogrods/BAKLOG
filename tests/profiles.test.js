import { describe, it, expect, beforeEach } from 'vitest';
import {
  ACTIVE_PROFILE_LS,
  prefsStorageKey,
  itadSnapshotStorageKey,
  profileScopedStorageKey,
  clearProfileLocalStorage,
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
    expect(profileScopedStorageKey('baklog-fetcher-auth-cooldown')).toBe(
      'baklog-fetcher-auth-cooldown:work',
    );
  });

  it('clearProfileLocalStorage removes suffixed keys for deleted profile', () => {
    localStorage.setItem(`${PREFS_KEY}:work`, '{}');
    localStorage.setItem('baklog-itad-snapshot:work', '{}');
    localStorage.setItem('steam-backlog-personal:work', '{}');
    localStorage.setItem('steam-backlog-manual-games:work', '[]');
    localStorage.setItem('baklog-fetcher-auth-cooldown:work', '{}');
    clearProfileLocalStorage('work');
    expect(localStorage.getItem(`${PREFS_KEY}:work`)).toBeNull();
    expect(localStorage.getItem('baklog-itad-snapshot:work')).toBeNull();
    expect(localStorage.getItem('steam-backlog-personal:work')).toBeNull();
    expect(localStorage.getItem('steam-backlog-manual-games:work')).toBeNull();
    expect(localStorage.getItem('baklog-fetcher-auth-cooldown:work')).toBeNull();
  });
});
