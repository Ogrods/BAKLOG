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

  it('bulk refresh is live in tierCompare, not coming soon', () => {
    const row = PRO_PROMO.tierCompare.find((r) => r.feature === 'Manual store refresh');
    expect(row).toBeTruthy();
    expect(row.pro).toMatch(/queue all stale/i);
    expect(row.pro).not.toMatch(/coming/i);
  });

  it('landing tier table bulk refresh cell matches PRO_PROMO', () => {
    const tableStart = LANDING_HTML.indexOf('aria-label="Free vs paid tier"');
    expect(tableStart).toBeGreaterThan(-1);
    const tableSlice = LANDING_HTML.slice(tableStart, tableStart + 4000);
    const rowMatch = tableSlice.match(
      /<th scope="row">Manual store refresh<\/th>\s*<td>[^<]*<\/td>\s*<td>([^<]+)<\/td>/,
    );
    expect(rowMatch).toBeTruthy();
    const promoRow = PRO_PROMO.tierCompare.find((r) => r.feature === 'Manual store refresh');
    expect(rowMatch[1].trim()).toBe(promoRow.pro);
  });

  it('only cloud sync and deal alerts use Coming in tierCompare pro column', () => {
    const comingRows = PRO_PROMO.tierCompare.filter((r) => /coming/i.test(String(r.pro)));
    expect(comingRows.map((r) => r.feature).sort()).toEqual([
      'Cloud sync',
      'Deal/watchlist alerts',
    ]);
  });

  it('trustPoints use canonical no telemetry by default wording', () => {
    const joined = PRO_PROMO.trustPoints.join(' ');
    expect(joined).toMatch(/no telemetry by default/i);
    expect(joined).not.toMatch(/\bZero telemetry\b/i);
  });
});
