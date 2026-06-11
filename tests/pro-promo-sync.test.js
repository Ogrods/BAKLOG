/** PRO_PROMO tier table stays aligned with landing/index.html paid tier rows. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PRO_PROMO } from '../js/sponsored-deals.js';

const LANDING_HTML = readFileSync('landing/index.html', 'utf8');

describe('PRO_PROMO sync with landing', () => {
  it('tierCompare covers the landing paid-tier table rows', () => {
    const rows = [...LANDING_HTML.matchAll(/<th scope="row">([^<]+)<\/th>/g)]
      .map((m) => m[1].replace(/&amp;/g, '&').trim());
    const paidTableStart = LANDING_HTML.indexOf('aria-label="Free vs paid tier"');
    expect(paidTableStart).toBeGreaterThan(-1);
    const tableSlice = LANDING_HTML.slice(paidTableStart, paidTableStart + 4000);
    const paidRows = [...tableSlice.matchAll(/<th scope="row">([^<]+)<\/th>/g)]
      .map((m) => m[1].replace(/&amp;/g, '&').trim());
    expect(paidRows.length).toBeGreaterThanOrEqual(8);
    const compareFeatures = new Set(PRO_PROMO.tierCompare.map((r) => r.feature));
    for (const row of paidRows) {
      expect(compareFeatures.has(row)).toBe(true);
    }
  });

  it('includes deal/watchlist alerts in Pro features', () => {
    const titles = PRO_PROMO.features.map((f) => f.title);
    expect(titles.some((t) => /deal\/watchlist alerts/i.test(t))).toBe(true);
  });

  it('boot tips no longer call Pro planned', () => {
    const indexHtml = readFileSync('index.html', 'utf8');
    expect(indexHtml).not.toMatch(/Pro \(planned/i);
  });
});
