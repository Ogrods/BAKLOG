/** Pro capabilities sync with PRO_PROMO tierCompare and landing Coming rows. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CAPABILITY_MARKETING } from '../js/pro-capabilities.js';
import { PRO_PROMO } from '../js/sponsored-deals.js';

const LANDING_HTML = readFileSync('landing/index.html', 'utf8');

describe('Pro capabilities marketing sync', () => {
  it('CAPABILITY_MARKETING keys cover tierCompare rows that map to capabilities', () => {
    const mapped = new Set(Object.values(CAPABILITY_MARKETING));
    for (const row of PRO_PROMO.tierCompare) {
      if (mapped.has(row.feature)) {
        expect(Object.values(CAPABILITY_MARKETING)).toContain(row.feature);
      }
    }
  });

  it('coming capabilities match landing tier table Coming cells', () => {
    const tableStart = LANDING_HTML.indexOf('aria-label="Free vs paid tier"');
    expect(tableStart).toBeGreaterThan(-1);
    const tableSlice = LANDING_HTML.slice(tableStart, tableStart + 5000);
    for (const [capId, label] of Object.entries(CAPABILITY_MARKETING)) {
      if (capId !== 'deal_watchlist_alerts') continue;
      const rowRe = new RegExp(
        `<th scope="row">${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}</th>[\\s\\S]*?<td>Coming</td>`,
        'i',
      );
      expect(tableSlice).toMatch(rowRe);
    }
  });

  it('cloud sync tier row is live in PRO_PROMO and landing', () => {
    const row = PRO_PROMO.tierCompare.find((r) => r.feature === 'Cloud sync');
    expect(row?.pro).toBe('Opt-in mirror');
    expect(row?.pro).not.toMatch(/coming/i);
    const tableStart = LANDING_HTML.indexOf('aria-label="Free vs paid tier"');
    const tableSlice = LANDING_HTML.slice(tableStart, tableStart + 5000);
    expect(tableSlice).toMatch(/Cloud sync[\s\S]*?Opt-in mirror/i);
  });

  it('live bulk refresh tier row does not say Coming', () => {
    const row = PRO_PROMO.tierCompare.find((r) => r.feature === 'Manual store refresh');
    expect(row?.pro).toMatch(/queue all stale/i);
    expect(row?.pro).not.toMatch(/coming/i);
  });

  it('PRO_PROMO cloud sync feature describes opt-in mirror', () => {
    const cloud = PRO_PROMO.features.find((f) => /cloud sync/i.test(f.title));
    expect(cloud?.desc).toMatch(/connections/i);
    expect(cloud?.desc).not.toMatch(/coming soon/i);
  });
});
