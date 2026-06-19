import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: vi.fn(() => false),
  isLocalProfilesEnabled: vi.fn(() => false),
  getAccountEmail: vi.fn(() => ''),
  getAccountProfileId: vi.fn(() => ''),
  signOutAccount: vi.fn(async () => {}),
}));

import {
  ACTIVE_PROFILE_LS,
  LS_ACTIVE_VIEW_SESSION,
  LS_FETCHER_LAST_SEQ,
  LS_LIBRARY_WATCH,
  LS_SPOTLIGHT_RECENT_KEYS,
  PROFILE_SCOPED_SESSION_KEYS,
  PROFILE_SCOPED_STORAGE_KEYS,
  activeViewSessionKey,
  claimsSnapshotStorageKey,
  colorThemeStorageKey,
  dashFailedCoversStorageKey,
  galleryModeStorageKey,
  knownLibraryKeysStorageKey,
  landscapeCoversStorageKey,
  libraryFirstSeenStorageKey,
  metricSeedSessionKey,
  metricsRenderedStorageKey,
  prefsStorageKey,
  proWelcomeSessionKey,
  statLayoutStorageKey,
  itadSnapshotStorageKey,
  untappedBatchMarkerStorageKey,
  profileScopedStorageKey,
  spotlightRecentKeysStorageKey,
  clearProfileLocalStorage,
  resetProfileClientCache,
  friendlyPinError,
  profileDisplayLabel,
  activeProfileId,
} from '../js/profiles.js';
import * as authGate from '../js/auth-gate.js';
import { COLOR_THEME_KEY, KNOWN_LIBRARY_KEYS_KEY, LIBRARY_FIRST_SEEN_KEY, MANUAL_KEY, PREFS_KEY, STORAGE_KEY } from '../js/state.js';

const PROFILE_SUFFIX = ':work';

/** Strip the active profile suffix to recover the reset-list base key. */
function storageBaseFromKey(fullKey) {
  expect(fullKey.endsWith(PROFILE_SUFFIX)).toBe(true);
  return fullKey.slice(0, -PROFILE_SUFFIX.length);
}

describe('profiles storage keys', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem(ACTIVE_PROFILE_LS, 'work');
  });

  it('defaults to default profile id with bare storage keys', () => {
    localStorage.removeItem(ACTIVE_PROFILE_LS);
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

  it('PROFILE_SCOPED lists cover every *StorageKey helper base', () => {
    const localHelpers = [
      prefsStorageKey,
      libraryFirstSeenStorageKey,
      knownLibraryKeysStorageKey,
      itadSnapshotStorageKey,
      claimsSnapshotStorageKey,
      spotlightRecentKeysStorageKey,
      colorThemeStorageKey,
      statLayoutStorageKey,
      galleryModeStorageKey,
      dashFailedCoversStorageKey,
      landscapeCoversStorageKey,
      metricsRenderedStorageKey,
      untappedBatchMarkerStorageKey,
    ];
    for (const helper of localHelpers) {
      expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(storageBaseFromKey(helper()));
    }
    const sessionHelpers = [activeViewSessionKey, metricSeedSessionKey, proWelcomeSessionKey];
    for (const helper of sessionHelpers) {
      expect(PROFILE_SCOPED_SESSION_KEYS).toContain(storageBaseFromKey(helper()));
    }
    for (const base of PROFILE_SCOPED_STORAGE_KEYS) {
      if (base === PREFS_KEY) continue;
      expect(profileScopedStorageKey(base)).toBe(`${base}${PROFILE_SUFFIX}`);
    }
    expect(new Set(PROFILE_SCOPED_STORAGE_KEYS).size).toBe(PROFILE_SCOPED_STORAGE_KEYS.length);
    expect(new Set(PROFILE_SCOPED_SESSION_KEYS).size).toBe(PROFILE_SCOPED_SESSION_KEYS.length);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(LIBRARY_FIRST_SEEN_KEY);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(KNOWN_LIBRARY_KEYS_KEY);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(LS_SPOTLIGHT_RECENT_KEYS);
    expect(PROFILE_SCOPED_SESSION_KEYS).toContain(LS_ACTIVE_VIEW_SESSION);
  });

  it('clearProfileLocalStorage removes suffixed localStorage and sessionStorage keys', () => {
    for (const base of PROFILE_SCOPED_STORAGE_KEYS) {
      localStorage.setItem(`${base}:work`, '{}');
    }
    for (const base of PROFILE_SCOPED_SESSION_KEYS) {
      sessionStorage.setItem(`${base}:work`, '{}');
    }
    clearProfileLocalStorage('work');
    for (const base of PROFILE_SCOPED_STORAGE_KEYS) {
      expect(localStorage.getItem(`${base}:work`)).toBeNull();
    }
    for (const base of PROFILE_SCOPED_SESSION_KEYS) {
      expect(sessionStorage.getItem(`${base}:work`)).toBeNull();
    }
    expect(sessionStorage.getItem(`${LS_FETCHER_LAST_SEQ}:work`)).toBeNull();
  });

  it('resetProfileClientCache clears stale scoped data for reused profile ids', () => {
    localStorage.setItem(`${PREFS_KEY}:work`, '{"stale":true}');
    localStorage.setItem(`${STORAGE_KEY}:work`, '{"old":"data"}');
    localStorage.setItem(`${LIBRARY_FIRST_SEEN_KEY}:work`, '{"steam:1":1000}');
    localStorage.setItem(`${KNOWN_LIBRARY_KEYS_KEY}:work`, '["steam:1"]');
    localStorage.setItem(`${LS_SPOTLIGHT_RECENT_KEYS}:work`, '["steam:2"]');
    sessionStorage.setItem(activeViewSessionKey('work'), 'library');
    resetProfileClientCache('work');
    expect(localStorage.getItem(`${PREFS_KEY}:work`)).toBeNull();
    expect(localStorage.getItem(`${STORAGE_KEY}:work`)).toBeNull();
    expect(localStorage.getItem(`${LIBRARY_FIRST_SEEN_KEY}:work`)).toBeNull();
    expect(localStorage.getItem(`${KNOWN_LIBRARY_KEYS_KEY}:work`)).toBeNull();
    expect(localStorage.getItem(`${LS_SPOTLIGHT_RECENT_KEYS}:work`)).toBeNull();
    expect(sessionStorage.getItem(activeViewSessionKey('work'))).toBeNull();
  });

  it('profileDisplayLabel appends id only when a label collides', () => {
    const profiles = [
      { id: 'work', label: 'Work' },
      { id: 'work-2', label: 'Work' },
      { id: 'play', label: 'Play' },
    ];
    expect(profileDisplayLabel(profiles[0], profiles)).toBe('Work (work)');
    expect(profileDisplayLabel(profiles[1], profiles)).toBe('Work (work-2)');
    expect(profileDisplayLabel(profiles[2], profiles)).toBe('Play');
  });

  it('profileDisplayLabel collision check is trimmed and case-insensitive', () => {
    const profiles = [
      { id: 'work', label: 'Work' },
      { id: 'work-2', label: 'work ' },
    ];
    expect(profileDisplayLabel(profiles[0], profiles)).toBe('Work (work)');
    expect(profileDisplayLabel(profiles[1], profiles)).toBe('work  (work-2)');
  });

  it('profileDisplayLabel falls back to id when label is empty', () => {
    const profiles = [{ id: 'work', label: '' }];
    expect(profileDisplayLabel(profiles[0], profiles)).toBe('work');
  });

  it('friendlyPinError maps server tokens to human copy and strips em dashes', () => {
    expect(friendlyPinError('incorrect_pin')).toBe('Incorrect PIN. Try again.');
    expect(friendlyPinError('pin_required')).toBe('Enter the PIN for this profile.');
    expect(friendlyPinError('too many PIN attempts \u2014 try again in 30 seconds')).toBe(
      'too many PIN attempts - try again in 30 seconds',
    );
    expect(friendlyPinError('')).toBe('Could not switch profile.');
  });

  it('uses localStorage active profile when local profiles enabled under account auth', () => {
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.isLocalProfilesEnabled.mockReturnValue(true);
    authGate.getAccountProfileId.mockReturnValue('supabase-uuid');
    localStorage.setItem(ACTIVE_PROFILE_LS, 'work');
    expect(activeProfileId()).toBe('work');
  });

  it('uses account profile id for storage keys when account auth without local profiles', () => {
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.isLocalProfilesEnabled.mockReturnValue(false);
    authGate.getAccountProfileId.mockReturnValue('supabase-uuid');
    localStorage.setItem(ACTIVE_PROFILE_LS, 'work');
    expect(activeProfileId()).toBe('supabase-uuid');
    expect(profileScopedStorageKey(LS_LIBRARY_WATCH)).toBe(`${LS_LIBRARY_WATCH}:supabase-uuid`);
  });

  it('falls back to account profile id in hybrid mode when localStorage unset', () => {
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.isLocalProfilesEnabled.mockReturnValue(true);
    authGate.getAccountProfileId.mockReturnValue('supabase-uuid');
    localStorage.removeItem(ACTIVE_PROFILE_LS);
    expect(activeProfileId()).toBe('supabase-uuid');
    expect(profileScopedStorageKey(STORAGE_KEY)).toBe(`${STORAGE_KEY}:supabase-uuid`);
  });
});
