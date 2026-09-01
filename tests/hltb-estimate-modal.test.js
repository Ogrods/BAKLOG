/**
 * HLTB pre-run estimate modal thresholds + ETA helpers.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  confirmHltbEstimate,
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

describe('confirmHltbEstimate markup', () => {
  afterEach(() => {
    document.getElementById('hltbEstimateModal')?.remove();
  });

  it('uses body/actions layout without purged mt-5', async () => {
    const pending = confirmHltbEstimate(
      { unchecked: 100, noMatch: 0 },
      { refresh: false },
    );
    const modal = document.getElementById('hltbEstimateModal');
    expect(modal).toBeTruthy();
    const html = modal.innerHTML;
    expect(html).toContain('app-modal-body');
    expect(html).toContain('app-modal-actions');
    expect(html).not.toContain('mt-5');
    expect(modal.querySelector('.hltb-estimate-cancel')).toBeTruthy();
    expect(modal.querySelector('.hltb-estimate-run')).toBeTruthy();
    modal.querySelector('.hltb-estimate-cancel')?.click();
    await expect(pending).resolves.toBe(false);
  });

  it('shows retry copy on Shift+click refresh', async () => {
    const pending = confirmHltbEstimate(
      { unchecked: 10, noMatch: 99 },
      { refresh: true },
    );
    const modal = document.getElementById('hltbEstimateModal');
    expect(modal?.textContent).toMatch(/retry 99 titles/i);
    modal.querySelector('.hltb-estimate-run')?.click();
    await expect(pending).resolves.toBe(true);
  });
});

describe('modal JS spacing hygiene', () => {
  it('does not use mt-5 in HLTB or update modal templates', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const root = path.resolve(import.meta.dirname, '..');
    for (const rel of ['js/hltb-estimate-modal.js', 'js/update-check.js']) {
      const src = fs.readFileSync(path.join(root, rel), 'utf8');
      expect(src, rel).not.toMatch(/\bmt-5\b/);
    }
  });
});
