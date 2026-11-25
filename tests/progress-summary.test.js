/**
 * Fetcher progress summary parser + soft-stall constant.
 */
import { describe, expect, it } from 'vitest';
import {
  parseProgressSummary,
  SOFT_STALL_NO_PROGRESS_MS,
} from '../js/fetcher/progress-summary.js';

describe('parseProgressSummary', () => {
  it('parses countable progress_line shapes', () => {
    expect(parseProgressSummary('[3/10] (30%) Steam library: Portal')).toBe(
      '[3/10] (30%) Steam library: Portal',
    );
    expect(parseProgressSummary('  · [42/100] (42%) EA library: Apex')).toContain('[42/100]');
    expect(parseProgressSummary('  · [42/100] (42%) EA library: Apex')).toContain('EA library');
  });

  it('parses elapsed still-running heartbeats', () => {
    expect(parseProgressSummary('Steam library - still running (90s)')).toBe(
      'Steam library (90s)',
    );
    expect(parseProgressSummary('  · probe - still running (25s)')).toBe('probe (25s)');
  });

  it('parses starting pulses', () => {
    expect(parseProgressSummary('Free claims feed download - starting')).toBe(
      'Free claims feed download - starting',
    );
  });

  it('returns null for unrelated lines', () => {
    expect(parseProgressSummary('INFO: routine')).toBeNull();
    expect(parseProgressSummary('')).toBeNull();
    expect(parseProgressSummary('[server] no output for 60s')).toBeNull();
  });
});

describe('soft stall constant', () => {
  it('is 30 seconds', () => {
    expect(SOFT_STALL_NO_PROGRESS_MS).toBe(30_000);
  });
});
