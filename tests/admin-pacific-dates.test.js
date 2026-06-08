import { describe, expect, it } from 'vitest';
import {
  formatEndsAt,
  isoFromPacificParts,
  pacificPartsFromIso,
} from '../admin/admin-pacific-dates.js';

describe('admin-pacific-dates', () => {
  it('round-trips a Pacific date-only value through ISO parts', () => {
    const iso = isoFromPacificParts('2026-06-08', null);
    expect(iso).toBeTruthy();
    const parts = pacificPartsFromIso(iso);
    expect(parts.date).toBe('2026-06-08');
    expect(parts.hasTime).toBe(false);
  });

  it('formatEndsAt returns em dash for empty values', () => {
    expect(formatEndsAt('')).toBe('—');
    expect(formatEndsAt(null)).toBe('—');
  });
});
