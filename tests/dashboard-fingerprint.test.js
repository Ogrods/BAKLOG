/**
 * Tests for js/dashboard.js::dashboardFingerprint — dashboard re-render inputs.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { loadSessionPrefs } from '../js/prefs.js';
import { dashboardFingerprint } from '../js/dashboard.js';

function resetState() {
  state.prefs = { quickWinMaxHours: 15 };
  state.sessionPrefs = loadSessionPrefs();
  state.itchGames = [];
  window._dataVersion = 0;
}

beforeEach(() => {
  resetState();
});

describe('dashboardFingerprint', () => {
  it('is stable when tracked inputs are unchanged', () => {
    const a = dashboardFingerprint();
    const b = dashboardFingerprint();
    expect(a).toBe(b);
  });

  it('changes when quickWinMaxHours, itch presence, itchHideNonGames, or data version change', () => {
    const base = dashboardFingerprint();

    state.prefs.quickWinMaxHours = 20;
    expect(dashboardFingerprint()).not.toBe(base);

    resetState();
    const b2 = dashboardFingerprint();
    state.itchGames = [{ store: 'itch', id: 'x', name: 'Demo' }];
    expect(dashboardFingerprint()).not.toBe(b2);

    resetState();
    const b3 = dashboardFingerprint();
    state.sessionPrefs.itchHideNonGames = false;
    expect(dashboardFingerprint()).not.toBe(b3);

    resetState();
    const b4 = dashboardFingerprint();
    window._dataVersion = 2;
    expect(dashboardFingerprint()).not.toBe(b4);
  });
});
