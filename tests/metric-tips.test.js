import { describe, it, expect } from 'vitest';
import {
  marqueeTip,
  insightTip,
  eyebrowTip,
  eyebrowVariant,
  EYEBROW_TIPS,
  EYEBROW_VARIANTS,
  METRIC_KEYS,
  metricKeyForLabel,
  metricKeyForInsight,
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

describe('metricKeyForLabel', () => {
  it('returns canonical METRIC_TIPS keys', () => {
    expect(metricKeyForLabel('backlog OPS')).toBe('backlog OPS');
    expect(metricKeyForLabel('games owned')).toBe('games owned');
  });

  it('resolves case-insensitive labels to canonical keys', () => {
    expect(metricKeyForLabel('hidden gems')).toBe('Hidden gems');
  });

  it('resolves dynamic Mendoza label via prefix', () => {
    expect(metricKeyForLabel('below Mendoza (78%)')).toBe('below Mendoza');
  });

  it('resolves added-in-year via prefix', () => {
    expect(metricKeyForLabel('added in 2026')).toBe('added in');
  });

  it('maps hot/warm/cold streak labels to finish streak', () => {
    expect(metricKeyForLabel('hot')).toBe('finish streak');
    expect(metricKeyForLabel('warm')).toBe('finish streak');
    expect(metricKeyForLabel('cold')).toBe('finish streak');
  });

  it('returns empty for unknown labels', () => {
    expect(metricKeyForLabel('totally unknown metric xyz')).toBe('');
  });

  it('METRIC_KEYS matches METRIC_TIPS object keys', () => {
    expect(METRIC_KEYS.length).toBeGreaterThan(100);
    expect(new Set(METRIC_KEYS).size).toBe(METRIC_KEYS.length);
  });

  it('resolves new untapped-metadata marquee labels', () => {
    const labels = [
      'Deck-ready %',
      'Proton platinum',
      'borked on Linux',
      'Proton trending up',
      'Deck-ready backlog',
      'platinums earned',
      'platinum hunt',
      'trophies earned',
      'PS5-native %',
      'PS4 holdouts',
      'top tag',
      'multiplayer share',
      'singleplayer backlog',
      'free itch games',
      'itch spend',
      'installed locally',
      'played in last 30d',
      'Metacritic 90+ club',
      'upcoming wishlist',
    ];
    for (const label of labels) {
      expect(metricKeyForLabel(label), label).toBe(label);
      expect(marqueeTip(label), label).not.toBe('');
    }
  });

  it('resolves batch-2 active-default marquee labels', () => {
    const labels = [
      'silver or native %',
      'Proton low confidence',
      'avg Proton score',
      'bought on sale',
      'paid itch games',
      'avg owned Steam price',
      'priority wishlist',
      'wishlist added this year',
      'wishlist stores',
      'last seen this week',
      'launcher installs',
      'HLTB low confidence',
      'co-op tagged only',
      'partial controller',
      'indie-tagged %',
      'avg trophy completion',
      'gamerscore completion %',
      'Metacritic 80+ unplayed',
      'biggest critic gap',
      'early access backlog',
      'double-dip backlog',
      'letter coverage %',
    ];
    for (const label of labels) {
      expect(metricKeyForLabel(label), label).toBeTruthy();
      expect(marqueeTip(label), label).not.toBe('');
    }
  });
});

describe('metricKeyForInsight', () => {
  it('resolves colon insights to canonical keys', () => {
    expect(metricKeyForInsight('Mendoza line: <strong>72%</strong>')).toBe('Mendoza line');
    expect(metricKeyForInsight('Top WAR pick: <strong>Foo</strong> · 2.1')).toBe('Top WAR pick');
  });

  it('resolves new untapped-metadata insight labels', () => {
    expect(metricKeyForInsight('Avg Metacritic: <strong>82</strong>')).toBe('Avg Metacritic');
    expect(metricKeyForInsight('Longest dormant: <strong>Foo</strong>')).toBe('Longest dormant');
    expect(insightTip('Avg Metacritic: <strong>82</strong>')).toMatch(/Metacritic/i);
    expect(metricKeyForInsight('Biggest critic gap: <strong>Foo</strong> · 25 pts')).toBe('biggest critic gap');
  });

  it('resolves pace insight without colon', () => {
    expect(metricKeyForInsight('~<strong>4.2</strong> yrs to clear at your pace')).toBe('to clear at your pace');
  });

  it('resolves previously-untooltipped insight pills via concept aliases', () => {
    expect(metricKeyForInsight('Playing since <strong>2015</strong>: <strong>Foo</strong>')).toBe('first PSN session');
    expect(metricKeyForInsight('Most sessions: <strong>Foo</strong> · 42')).toBe('most PSN sessions');
    expect(metricKeyForInsight('PSN sessions: <strong>120</strong> total')).toBe('PSN sessions total');
    expect(metricKeyForInsight('PSN tenure: <strong>6.3</strong> yrs since first session')).toBe('PSN library tenure');
    expect(metricKeyForInsight('Will you die first? <strong>Backlog wins</strong> · finish by age 80')).toBe('Will you die first?');
  });
});

describe('insightTip', () => {
  it('resolves Mendoza line insight from HTML', () => {
    const tip = insightTip('Mendoza line: <strong>72%</strong>');
    expect(tip).toMatch(/median.*backlog/i);
    expect(tip).toMatch(/review %/i);
  });

  it('explains WAR with review % and Mendoza definitions', () => {
    const tip = insightTip('Top WAR pick: <strong>Foo</strong> · 2.1');
    expect(tip).toMatch(/review %/i);
    expect(tip).toMatch(/Mendoza/i);
    expect(tip).toMatch(/Steam/i);
    expect(eyebrowTip('MVP pick')).toMatch(/review %/i);
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

  it('gives every insight pill a tooltip (no empty inspiration pills)', () => {
    const insights = [
      'Playing since <strong>2015</strong>: <strong>Foo</strong>',
      'Most sessions: <strong>Foo</strong> · 42',
      'PSN sessions: <strong>120</strong> total',
      'PSN tenure: <strong>6.3</strong> yrs since first session',
      'Will you die first? <strong>Backlog wins</strong> · finish by age 80',
    ];
    for (const html of insights) {
      expect(insightTip(html), html).not.toBe('');
    }
    expect(insightTip('Playing since <strong>2015</strong>: <strong>Foo</strong>')).toMatch(/PSN|first_played|earliest/i);
    expect(insightTip('Will you die first? <strong>Backlog wins</strong> · finish by age 80')).toMatch(/backlog|life expectancy/i);
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
