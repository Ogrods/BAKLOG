/** Guardrails: queued bulk refresh copy stays "live on Pro", not "coming soon". */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PRO_PROMO } from '../js/sponsored-deals.js';

const FAQ = readFileSync('guide/faq.md', 'utf8');
const README = readFileSync('README.md', 'utf8');
const DASH_GUIDE = readFileSync('guide/using-the-dashboard.md', 'utf8');
const INDEX_HTML = readFileSync('index.html', 'utf8');
const TIPS = readFileSync('js/tips.js', 'utf8');

describe('Pro bulk refresh copy guards', () => {
  it('FAQ and README describe bulk refresh as live on Pro', () => {
    expect(FAQ).toMatch(/queued bulk refresh/i);
    expect(FAQ).toMatch(/live on Pro/i);
    expect(README).toMatch(/queued bulk refresh/i);
    expect(README).toMatch(/\*\*Live:\*\*/i);
    for (const [name, text] of [['faq', FAQ], ['readme', README]]) {
      const bulkLines = text.split('\n').filter((line) => /bulk refresh/i.test(line));
      for (const line of bulkLines) {
        expect(line, `${name} bulk line`).not.toMatch(/coming soon/i);
      }
    }
  });

  it('dashboard guide lists queued bulk refresh under paid tier', () => {
    expect(DASH_GUIDE).toMatch(/queued bulk refresh/i);
    expect(DASH_GUIDE).not.toMatch(/bulk refresh.*coming/i);
  });

  it('boot tips do not call bulk refresh planned', () => {
    expect(INDEX_HTML).not.toMatch(/bulk refresh.*planned/i);
    expect(TIPS).not.toMatch(/bulk refresh.*planned/i);
    expect(TIPS).not.toMatch(/bulk refresh.*coming/i);
  });

  it('PRO_PROMO feature card describes bulk refresh without coming soon', () => {
    const bulk = PRO_PROMO.features.find((f) => /queued bulk refresh/i.test(f.title));
    expect(bulk).toBeTruthy();
    expect(bulk.desc).not.toMatch(/coming/i);
  });
});
