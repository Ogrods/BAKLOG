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
  LS_FETCHER_LAST_SEQ,
  LS_LIBRARY_WATCH,
  PROFILE_SCOPED_SESSION_KEYS,
  PROFILE_SCOPED_STORAGE_KEYS,
  prefsStorageKey,
  itadSnapshotStorageKey,
  profileScopedStorageKey,
  clearProfileLocalStorage,
  activeProfileId,
} from '../js/profiles.js';
import * as authGate from '../js/auth-gate.js';
import { MANUAL_KEY, PREFS_KEY, STORAGE_KEY } from '../js/state.js';

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

  it('PROFILE_SCOPED_STORAGE_KEYS lists every localStorage base key', () => {
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(PREFS_KEY);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(STORAGE_KEY);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(MANUAL_KEY);
    expect(PROFILE_SCOPED_STORAGE_KEYS).toContain(LS_LIBRARY_WATCH);
    expect(new Set(PROFILE_SCOPED_STORAGE_KEYS).size).toBe(PROFILE_SCOPED_STORAGE_KEYS.length);
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
    expect(activeProfileId()).toBe('supabase-uuid');
    expect(profileScopedStorageKey(STORAGE_KEY)).toBe(`${STORAGE_KEY}:supabase-uuid`);
  });
});
