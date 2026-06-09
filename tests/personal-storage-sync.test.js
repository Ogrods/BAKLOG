/** Cross-tab personal JSON sync via storage events (Phase 3 EVT-04 partial). */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

describe('installPersonalStorageSync', () => {
  let state;
  let installPersonalStorageSync;
  let personalStorageKey;

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    ({ state } = await import('../js/state.js'));
    const personalStorage = await import('../js/personal-storage.js');
    installPersonalStorageSync = personalStorage.installPersonalStorageSync;
    personalStorageKey = personalStorage.personalStorageKey;
    state.personal = { 'steam:1': { status: 'backlog' } };
    localStorage.setItem(personalStorageKey(), JSON.stringify(state.personal));
    installPersonalStorageSync();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('applies personal from another tab when local save is not pending', () => {
    const incoming = { 'steam:2': { status: 'playing' } };
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: personalStorageKey(),
        newValue: JSON.stringify(incoming),
        storageArea: localStorage,
      }),
    );
    expect(state.personal).toEqual(incoming);
  });

  it('ignores storage events while a debounced save is pending', async () => {
    const { savePersonal } = await import('../js/personal-storage.js');
    state.personal['steam:1'].status = 'next';
    savePersonal();
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: personalStorageKey(),
        newValue: JSON.stringify({ 'steam:9': { status: 'backlog' } }),
        storageArea: localStorage,
      }),
    );
    expect(state.personal['steam:1'].status).toBe('next');
  });
});
