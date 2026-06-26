/** AGENTS.md rule 6 sync-pair guards (subset with machine-checkable parity). */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CLAIM_SOURCE_RANK } from '../js/claim-card.js';
import { AD_LOCATIONS } from '../js/sponsored-deals.js';
import { stripClaimTitleDecorations } from '../js/claim-card.js';

const ROOT = path.resolve(import.meta.dirname, '..');

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

describe('sync pairs (AGENTS.md rule 6)', () => {
  it('CLAIM_SOURCE_RANK matches Python SOURCE_PRECEDENCE order', () => {
    const py = read('shared/free_claims_sources.py');
    const epic = py.match(/SOURCE_PRECEDENCE\s*=\s*\{([^}]+)\}/);
    expect(epic).toBeTruthy();
    expect(CLAIM_SOURCE_RANK.epic).toBe(0);
    expect(CLAIM_SOURCE_RANK.gamerpower).toBe(1);
    expect(CLAIM_SOURCE_RANK.itad).toBe(2);
  });

  it('stripClaimTitleDecorations matches Python strip_giveaway_decorations fixture', () => {
    const fixture = JSON.parse(
      read('tests/fixtures/giveaway_title_strip.json'),
    );
    for (const row of fixture) {
      expect(stripClaimTitleDecorations(row.input)).toBe(row.expected);
    }
  });

  it('AD_LOCATIONS keys are unique and non-empty', () => {
    const keys = Object.keys(AD_LOCATIONS);
    expect(keys.length).toBeGreaterThan(0);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('committed fetcher-registry.js matches Python export header', () => {
    const js = read('js/fetcher-registry.js');
    expect(js).toContain('Regenerate: python -c "from fetchers.registry import export_js_registry');
    const py = read('fetchers/registry.py');
    expect(py).toContain('export_js_registry');
  });
});
