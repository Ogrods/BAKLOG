import { describe, expect, it } from 'vitest';
import {
  MIRROR_VIRTUAL_THRESHOLD,
  computeMirrorVirtualRange,
  usesMirrorVirtualScroll,
} from '../landing/mirror-virtual.js';

describe('mirror-virtual', () => {
  it('uses virtual scroll only above the threshold', () => {
    expect(usesMirrorVirtualScroll(MIRROR_VIRTUAL_THRESHOLD)).toBe(false);
    expect(usesMirrorVirtualScroll(MIRROR_VIRTUAL_THRESHOLD + 1)).toBe(true);
  });

  it('returns an empty window for empty lists', () => {
    expect(computeMirrorVirtualRange(0, {
      scrollY: 0,
      viewportH: 800,
      rowHeight: 40,
      tableTop: 100,
    })).toEqual({ start: 0, end: 0 });
  });

  it('windows around the viewport with overscan', () => {
    const range = computeMirrorVirtualRange(2000, {
      scrollY: 2000,
      viewportH: 800,
      rowHeight: 40,
      tableTop: 200,
      overscan: 10,
    });
    // First visible index ≈ (2000-200)/40 = 45; with overscan start ≈ 35
    expect(range.start).toBeGreaterThanOrEqual(30);
    expect(range.start).toBeLessThanOrEqual(45);
    expect(range.end).toBeGreaterThan(range.start);
    expect(range.end - range.start).toBeLessThan(80);
    expect(range.end).toBeLessThanOrEqual(2000);
  });

  it('clamps to list bounds near the end', () => {
    const range = computeMirrorVirtualRange(100, {
      scrollY: 50_000,
      viewportH: 800,
      rowHeight: 40,
      tableTop: 0,
      overscan: 5,
    });
    expect(range.end).toBe(100);
    expect(range.start).toBeLessThan(100);
    expect(range.start).toBeGreaterThanOrEqual(0);
  });
});
