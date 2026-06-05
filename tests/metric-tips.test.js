import { describe, it, expect } from 'vitest';
import {
  marqueeTip,
  insightTip,
  eyebrowTip,
  eyebrowVariant,
  EYEBROW_TIPS,
  EYEBROW_VARIANTS,
} from '../js/metric-tips.js';

describe('marqueeTip', () => {
  it('returns formula copy for sabermetric labels', () => {
    const ops = marqueeTip('backlog OPS');
    expect(ops.length).toBeGreaterThan(0);
    expect(ops).toMatch(/OBP|SLG/i);
    const obp = marqueeTip('start rate (OBP)');
    expect(obp).toMatch(/touched/i);
  });

  it('resolves dynamic Mendoza label via prefix fallback', () => {
    const tip = marqueeTip('below Mendoza (78%)');
    expect(tip).toMatch(/Mendoza/i);
  });

  it('resolves added-in-year via prefix fallback', () => {
    const tip = marqueeTip('added in 2026');
    expect(tip).toMatch(/calendar year/i);
  });

  it('returns empty for unknown labels', () => {
    expect(marqueeTip('totally unknown metric xyz')).toBe('');
  });

  it('resolves hidden gems regardless of case', () => {
    expect(marqueeTip('hidden gems')).toMatch(/90%/);
  });
});

describe('insightTip', () => {
  it('resolves Mendoza line insight from HTML', () => {
    const tip = insightTip('Mendoza line: <strong>72%</strong>');
    expect(tip).toMatch(/median backlog/i);
  });

  it('resolves colon-less pace insight', () => {
    const tip = insightTip('~<strong>4.2</strong> yrs to clear at your pace');
    expect(tip.length).toBeGreaterThan(0);
  });

  it('resolves the time-capsule "Added ... still untouched" insight', () => {
    const tip = insightTip('Added <strong>2019</strong>, still untouched: <strong>Foo</strong>');
    expect(tip.length).toBeGreaterThan(0);
    expect(tip).toMatch(/untouched|time capsule/i);
  });

  it('returns empty for unknown insight', () => {
    expect(insightTip('Unknown nonsense metric: <strong>1</strong>')).toBe('');
  });
});

describe('eyebrowTip', () => {
  it('explains cryptic baseball eyebrows', () => {
    expect(eyebrowTip('Barrel')).toMatch(/85%|≤12h|short/i);
    expect(eyebrowTip('Completionist')).toMatch(/100%|complete/i);
    expect(marqueeTip('platinum potential')).toMatch(/80|99|12h/i);
  });

  it('explains creative superlative eyebrows', () => {
    expect(eyebrowTip('Whale')).toMatch(/priciest|MSRP/i);
    expect(eyebrowTip('Gathering dust')).toMatch(/longest|unplayed|shelf/i);
    expect(eyebrowTip('Guilty pleasure')).toMatch(/lowest-rated|finished/i);
  });

  it('returns empty for unknown or missing eyebrows', () => {
    expect(eyebrowTip('Spotlight')).toBe('');
    expect(eyebrowTip('')).toBe('');
    expect(eyebrowTip(undefined)).toBe('');
  });

  it('every documented eyebrow has non-trivial copy', () => {
    for (const [eyebrow, tip] of Object.entries(EYEBROW_TIPS)) {
      expect(tip.length, eyebrow).toBeGreaterThan(10);
    }
  });
});

function wordCount(label) {
  return String(label).trim().split(/\s+/).length;
}

describe('eyebrowVariant', () => {
  it('returns a member of the variant list for known categories', () => {
    const v = eyebrowVariant('Barrel', 'steam:42');
    expect(EYEBROW_VARIANTS.Barrel).toContain(v);
  });

  it('is deterministic for the same seed', () => {
    expect(eyebrowVariant('Replay', 'steam:1')).toBe(eyebrowVariant('Replay', 'steam:1'));
  });

  it('can vary across different seeds', () => {
    const seen = new Set();
    for (let i = 0; i < 20; i++) {
      seen.add(eyebrowVariant('Barrel', `steam:${i}`));
    }
    expect(seen.size).toBeGreaterThan(1);
  });

  it('uses different labels for the same category on different games', () => {
    const labels = new Set(
      Array.from({ length: 12 }, (_, i) => eyebrowVariant('Quick win', `steam:${i}`)),
    );
    expect(labels.size).toBeGreaterThan(1);
  });

  it('returns canonical for unknown categories', () => {
    expect(eyebrowVariant('Spotlight', 'steam:1')).toBe('Spotlight');
  });

  it('every variant entry lists canonical first and uses short labels', () => {
    for (const [canonical, variants] of Object.entries(EYEBROW_VARIANTS)) {
      expect(variants[0], canonical).toBe(canonical);
      expect(variants.length, canonical).toBeGreaterThanOrEqual(2);
      for (const label of variants) {
        expect(wordCount(label), `${canonical}: ${label}`).toBeLessThanOrEqual(3);
      }
    }
  });

  it('every variant canonical has an EYEBROW_TIPS entry (no cryptic label ships without a tip)', () => {
    for (const canonical of Object.keys(EYEBROW_VARIANTS)) {
      expect(EYEBROW_TIPS[canonical], canonical).toBeTruthy();
    }
  });
});
