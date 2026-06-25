import { describe, expect, it } from 'vitest';
import { heroCountRollMs } from '../js/dashboard-shared.js';

describe('heroCountRollMs', () => {
  it('returns ~750ms for a single +1 popup train', () => {
    expect(heroCountRollMs(1, 1)).toBeGreaterThanOrEqual(750);
    expect(heroCountRollMs(1, 1)).toBeLessThanOrEqual(900);
  });

  it('scales up for large deltas and caps at 3500ms', () => {
    const small = heroCountRollMs(1, 1);
    const large = heroCountRollMs(100, 10);
    expect(large).toBeGreaterThan(small);
    expect(heroCountRollMs(500, 10)).toBeLessThanOrEqual(3500);
  });

  it('covers full popup train length for multi-popup bursts', () => {
    const train = (10 - 1) * 300 + 500;
    expect(heroCountRollMs(50, 10)).toBeGreaterThanOrEqual(train);
  });
});
