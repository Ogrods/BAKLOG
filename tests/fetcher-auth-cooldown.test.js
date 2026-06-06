/** Chip-level auth-failure backoff (escalating 5m -> 15m -> 60m). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  authCooldownDurationMs,
  noteAuthCooldownStrike,
  authCooldownRemainingMs,
  clearAuthCooldown,
} from '../js/fetcher-health.js';
import { ACTIVE_PROFILE_LS, LS_FETCHER_AUTH_COOLDOWN } from '../js/profiles.js';

describe('authCooldownDurationMs', () => {
  it('escalates 5m -> 15m -> 60m and caps at the top step', () => {
    expect(authCooldownDurationMs(1)).toBe(5 * 60_000);
    expect(authCooldownDurationMs(2)).toBe(15 * 60_000);
    expect(authCooldownDurationMs(3)).toBe(60 * 60_000);
    expect(authCooldownDurationMs(4)).toBe(60 * 60_000);
  });

  it('floors at the first step for non-positive strikes', () => {
    expect(authCooldownDurationMs(0)).toBe(5 * 60_000);
  });
});

describe('chip auth cooldown lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    clearAuthCooldown('psn');
  });
  afterEach(() => {
    clearAuthCooldown('psn');
    vi.useRealTimers();
  });

  it('starts clear, arms on a strike, escalates, then self-expires', () => {
    expect(authCooldownRemainingMs('psn')).toBe(0);

    noteAuthCooldownStrike('psn');
    const first = authCooldownRemainingMs('psn');
    expect(first).toBeGreaterThan(0);
    expect(first).toBeLessThanOrEqual(5 * 60_000);

    // A second consecutive failure escalates to the 15m tier.
    noteAuthCooldownStrike('psn');
    expect(authCooldownRemainingMs('psn')).toBeGreaterThan(5 * 60_000);

    // Past the longest window it clears itself.
    vi.advanceTimersByTime(60 * 60_000 + 1_000);
    expect(authCooldownRemainingMs('psn')).toBe(0);
  });

  it('clears on demand (successful run / reconnect path)', () => {
    noteAuthCooldownStrike('psn');
    expect(authCooldownRemainingMs('psn')).toBeGreaterThan(0);
    clearAuthCooldown('psn');
    expect(authCooldownRemainingMs('psn')).toBe(0);
  });

  it('loads cooldowns from the active profile key after ensureProfileScopedFetcherState', async () => {
    vi.resetModules();
    vi.useRealTimers();
    localStorage.clear();
    localStorage.setItem(ACTIVE_PROFILE_LS, 'work');
    const key = `${LS_FETCHER_AUTH_COOLDOWN}:work`;
    const until = Date.now() + 60_000;
    localStorage.setItem(key, JSON.stringify({ psn: { until, strikes: 1 } }));
    const mod = await import('../js/fetcher-health.js');
    mod.ensureProfileScopedFetcherState();
    expect(mod.authCooldownRemainingMs('psn')).toBeGreaterThan(0);
    mod.clearAuthCooldown('psn');
  });
});
