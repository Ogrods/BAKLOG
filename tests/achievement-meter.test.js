/**
 * Tests for js/achievement-meter.js — the metered deep-sync quota ledger.
 *
 * Scope: the rules that gate a paid-ish action (deep achievement re-pull) on the
 * free tier — daily free allowance, credit fallback, day rollover reset, and the
 * honest gating message when exhausted. A regression here either gives away
 * unlimited syncs (no metering) or locks out a user who still has allowance.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  FREE_DAILY,
  meterSummary,
  canDeepSync,
  consumeDeepSync,
  addCredits,
  meterLabel,
  dayKey,
  _resetMeter,
} from '../js/achievement-meter.js';

beforeEach(() => {
  _resetMeter();
});

afterEach(() => {
  vi.useRealTimers();
  _resetMeter();
});

describe('initial state', () => {
  it('starts with the full daily free allowance', () => {
    const s = meterSummary();
    expect(s.freeDaily).toBe(FREE_DAILY);
    expect(s.freeRemaining).toBe(FREE_DAILY);
    expect(s.usedToday).toBe(0);
    expect(s.credits).toBe(0);
  });

  it('can deep sync on a fresh ledger', () => {
    expect(canDeepSync()).toBe(true);
  });
});

describe('consumeDeepSync', () => {
  it('spends the free allowance first', () => {
    const res = consumeDeepSync('steam:1');
    expect(res.ok).toBe(true);
    expect(res.source).toBe('free');
    expect(meterSummary().freeRemaining).toBe(FREE_DAILY - 1);
  });

  it('records the last sync time per title', () => {
    consumeDeepSync('psn:42');
    expect(meterSummary().lastSyncByTitle['psn:42']).toBeGreaterThan(0);
  });

  it('falls back to credits once the free allowance is spent', () => {
    for (let i = 0; i < FREE_DAILY; i++) consumeDeepSync(`g${i}`);
    expect(canDeepSync()).toBe(false);
    addCredits(2);
    expect(canDeepSync()).toBe(true);
    const res = consumeDeepSync('extra');
    expect(res.ok).toBe(true);
    expect(res.source).toBe('credit');
    expect(meterSummary().credits).toBe(1);
  });

  it('gates with reason "exhausted" when free + credits are gone', () => {
    for (let i = 0; i < FREE_DAILY; i++) consumeDeepSync(`g${i}`);
    const res = consumeDeepSync('blocked');
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('exhausted');
  });
});

describe('day rollover', () => {
  it('resets the free allowance when the calendar day changes', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-07T10:00:00'));
    for (let i = 0; i < FREE_DAILY; i++) consumeDeepSync(`g${i}`);
    expect(canDeepSync()).toBe(false);

    vi.setSystemTime(new Date('2026-06-08T09:00:00'));
    expect(meterSummary().freeRemaining).toBe(FREE_DAILY);
    expect(canDeepSync()).toBe(true);
  });

  it('keeps purchased credits across the day boundary', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-07T10:00:00'));
    addCredits(3);
    vi.setSystemTime(new Date('2026-06-08T09:00:00'));
    expect(meterSummary().credits).toBe(3);
  });
});

describe('addCredits', () => {
  it('ignores non-positive amounts', () => {
    expect(addCredits(0).credits).toBe(0);
    expect(addCredits(-5).credits).toBe(0);
    expect(addCredits('nope').credits).toBe(0);
  });
});

describe('meterLabel', () => {
  it('shows free syncs remaining', () => {
    expect(meterLabel()).toMatch(/free deep sync/);
  });

  it('shows credits when the free allowance is spent', () => {
    for (let i = 0; i < FREE_DAILY; i++) consumeDeepSync(`g${i}`);
    addCredits(2);
    expect(meterLabel()).toMatch(/credits available/);
  });

  it('shows the planned-paid-tier message when fully exhausted', () => {
    for (let i = 0; i < FREE_DAILY; i++) consumeDeepSync(`g${i}`);
    expect(meterLabel()).toMatch(/paid tier \(planned\)/);
  });
});

describe('dayKey', () => {
  it('formats local YYYY-MM-DD', () => {
    expect(dayKey(new Date('2026-01-05T12:00:00'))).toBe('2026-01-05');
  });
});
