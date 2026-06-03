import { describe, expect, it } from 'vitest';
import { formatReleaseDate } from '../../js/dom-util.js';

describe('formatReleaseDate', () => {
  it('formats YYYY-MM-DD', () => {
    const out = formatReleaseDate('2024-03-28');
    expect(out).toMatch(/Mar/);
    expect(out).toMatch(/28/);
    expect(out).toMatch(/2024/);
  });

  it('formats ISO timestamp', () => {
    const out = formatReleaseDate('2017-11-23T09:14:28.460000+00:00');
    expect(out).toMatch(/Nov/);
    expect(out).toMatch(/2017/);
    expect(out).not.toContain('T09');
  });

  it('returns em dash for empty', () => {
    expect(formatReleaseDate(null)).toBe('—');
    expect(formatReleaseDate('')).toBe('—');
  });
});
