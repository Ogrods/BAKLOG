/**
 * HLTB pre-run estimate modal thresholds + ETA helpers.
 */
import { describe, expect, it } from 'vitest';
import {
  estimateHltbSeconds,
  hltbPendingLookupCount,
  HLTB_LOOKUP_SEC,
  HLTB_MODAL_ETA_MIN_MINUTES,
  HLTB_MODAL_UNCHECKED_MIN,
  shouldConfirmHltbRun,
} from '../js/hltb-estimate-modal.js';

describe('hltb estimate modal helpers', () => {
  it('counts unchecked only unless refresh retries noMatch', () => {
    const pending = { unchecked: 10, noMatch: 40, retry: 0 };
    expect(hltbPendingLookupCount(pending)).toBe(10);
    expect(hltbPendingLookupCount(pending, { refresh: true })).toBe(50);
  });

  it('matches enricher ETA seconds per lookup', () => {
    expect(HLTB_LOOKUP_SEC).toBeCloseTo(7.65);
    expect(estimateHltbSeconds(100)).toBeCloseTo(765);
  });

  it('requires confirm for large unchecked backlog', () => {
    expect(shouldConfirmHltbRun({ unchecked: HLTB_MODAL_UNCHECKED_MIN, noMatch: 0 })).toBe(false);
    expect(shouldConfirmHltbRun({ unchecked: HLTB_MODAL_UNCHECKED_MIN + 1, noMatch: 0 })).toBe(true);
  });

  it('requires confirm when ETA exceeds threshold', () => {
    const need = Math.ceil((HLTB_MODAL_ETA_MIN_MINUTES * 60) / HLTB_LOOKUP_SEC) + 1;
    expect(shouldConfirmHltbRun({ unchecked: need, noMatch: 0 })).toBe(true);
  });

  it('requires confirm for large Shift+click miss retries', () => {
    expect(shouldConfirmHltbRun({ unchecked: 0, noMatch: 49 }, { refresh: true })).toBe(false);
    expect(shouldConfirmHltbRun({ unchecked: 0, noMatch: 50 }, { refresh: true })).toBe(true);
  });
});
