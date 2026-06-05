import { describe, expect, it } from 'vitest';
import { countUpDurationForDelta, easeInOutCubic } from '../js/dashboard-shared.js';

describe('countUpDurationForDelta', () => {
  it('returns 450ms for a single-item add', () => {
    expect(countUpDurationForDelta(1)).toBe(450);
  });

  it('scales gently for medium deltas', () => {
    expect(countUpDurationForDelta(25)).toBe(650);
    expect(countUpDurationForDelta(100)).toBe(900);
  });

  it('caps at 1300ms for large imports', () => {
    expect(countUpDurationForDelta(324)).toBe(1300);
    expect(countUpDurationForDelta(2000)).toBe(1300);
  });

  it('treats negative deltas as absolute magnitude', () => {
    expect(countUpDurationForDelta(-1)).toBe(450);
  });
});

describe('easeInOutCubic', () => {
  it('starts at 0 and ends at 1', () => {
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(1)).toBe(1);
  });

  it('is symmetric around the midpoint', () => {
    expect(easeInOutCubic(0.25)).toBeCloseTo(1 - easeInOutCubic(0.75), 5);
  });
});
