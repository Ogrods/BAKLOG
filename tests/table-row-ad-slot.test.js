/**
 * Sponsored table-row ad slot: fixed default vs drill/alpha anchor (2 rows above).
 */

import { describe, expect, it, beforeEach } from 'vitest';
import {
  clearRowAdAnchor,
  setRowAdAnchor,
  sponsoredTableSlotForTest,
} from '../js/table-ui.js';

beforeEach(() => {
  clearRowAdAnchor();
});

describe('sponsoredTableSlotForTest', () => {
  it('uses fixed slot 5 on long lists when no anchor is set', () => {
    expect(sponsoredTableSlotForTest(100)).toBe(5);
  });

  it('uses the last row on short lists when no anchor is set', () => {
    expect(sponsoredTableSlotForTest(3)).toBe(2);
  });

  it('places the ad 1 row above the drill anchor', () => {
    setRowAdAnchor(50);
    expect(sponsoredTableSlotForTest(100)).toBe(49);
  });

  it('clamps the drill slot to index 0', () => {
    setRowAdAnchor(0);
    expect(sponsoredTableSlotForTest(100)).toBe(0);
  });

  it('restores the fixed slot after clearRowAdAnchor', () => {
    setRowAdAnchor(50);
    clearRowAdAnchor();
    expect(sponsoredTableSlotForTest(100)).toBe(5);
  });
});
