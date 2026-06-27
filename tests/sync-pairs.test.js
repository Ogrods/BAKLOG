/** AGENTS.md rule 6 sync-pair guards (consolidated entry + machine-checkable parity). */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CLAIM_SOURCE_RANK } from '../js/claim-card.js';
import { AD_LOCATIONS } from '../js/sponsored-deals.js';
import { stripClaimTitleDecorations } from '../js/claim-card.js';
import { STORE_BRAND_COLORS } from '../js/store-brand-colors.js';

const ROOT = path.resolve(import.meta.dirname, '..');

/** Dedicated parity modules (also rule 6): library-noise-parity.test.js, blurb-sanitize-parity.test.js, ad-locations-sync.test.js, pro-promo-sync.test.js */

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

function parsePythonDictLiteral(text) {
  return JSON.parse(text.replace(/'/g, '"'));
}

describe('sync pairs (AGENTS.md rule 6)', () => {
  it('CLAIM_SOURCE_RANK matches Python SOURCE_PRECEDENCE exactly', () => {
    const py = read('shared/free_claims_sources.py');
    const m = py.match(/SOURCE_PRECEDENCE\s*=\s*(\{[^}]+\})/);
    expect(m).toBeTruthy();
    const precedence = parsePythonDictLiteral(m[1]);
    for (const [source, rank] of Object.entries(precedence)) {
      expect(CLAIM_SOURCE_RANK[source], source).toBe(rank);
    }
    for (const source of Object.keys(CLAIM_SOURCE_RANK)) {
      if (source === 'manual' || source === 'other') continue;
      expect(precedence, `missing ${source} in SOURCE_PRECEDENCE`).toHaveProperty(source);
    }
  });

  it('stripClaimTitleDecorations matches Python strip_giveaway_decorations fixture', () => {
    const fixture = JSON.parse(
      read('tests/fixtures/giveaway_title_strip.json'),
    );
    for (const row of fixture) {
      expect(stripClaimTitleDecorations(row.input)).toBe(row.expected);
    }
  });

  it('STORE_BRAND_COLORS matches app.css --brand-* tokens', () => {
    const css = read('app.css');
    for (const [store, hex] of Object.entries(STORE_BRAND_COLORS)) {
      if (store === 'other' || store === 'manual') continue;
      const varName = `--brand-${store.replace(/_/g, '-')}`;
      const re = new RegExp(`${varName.replace(/-/g, '\\-')}:\\s*(#[0-9a-fA-F]{3,8})`);
      const match = css.match(re);
      expect(match, varName).toBeTruthy();
      expect(match[1].toLowerCase()).toBe(hex.toLowerCase());
    }
  });

  it('landing/marquee-speed.js MARQUEE_PX_PER_SEC matches js/marquee-speed.js', () => {
    const landing = read('landing/marquee-speed.js');
    const app = read('js/marquee-speed.js');
    const landingVal = landing.match(/MARQUEE_PX_PER_SEC\s*=\s*(\d+)/)?.[1];
    const appVal = app.match(/MARQUEE_PX_PER_SEC\s*=\s*(\d+)/)?.[1];
    expect(landingVal).toBeTruthy();
    expect(appVal).toBe(landingVal);
  });

  it('AD_LOCATIONS keys are unique and non-empty', () => {
    const keys = Object.keys(AD_LOCATIONS);
    expect(keys.length).toBeGreaterThan(0);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('committed fetcher-registry.js matches Python export (see test_fetcher_registry_drift.py)', () => {
    const js = read('js/fetcher-registry.js');
    expect(js).toContain('Regenerate: python -c "from fetchers.registry import export_js_registry');
    const py = read('fetchers/registry.py');
    expect(py).toContain('export_js_registry');
  });
});
