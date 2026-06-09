import { describe, expect, it } from 'vitest';
import { computeAutoDisabled } from '../js/metrics-rendered.js';

describe('metrics-rendered computeAutoDisabled', () => {
  const catalog = ['games owned', 'stores', 'gamerscore earned', 'first PSN session'];

  it('moves every no-data metric to disabled', () => {
    const next = computeAutoDisabled(catalog, ['games owned', 'stores'], []);
    expect(next).toEqual(['gamerscore earned', 'first PSN session']);
  });

  it('preserves manual hides of data-having metrics', () => {
    const next = computeAutoDisabled(catalog, ['games owned', 'stores'], ['stores']);
    expect(next).toEqual(['stores', 'gamerscore earned', 'first PSN session']);
  });

  it('does not re-enable a no-data metric the user tried to keep used', () => {
    // 'first PSN session' has no data; even if the user removed it from disabled,
    // the auto-sync re-disables it because it can never render.
    const next = computeAutoDisabled(catalog, ['games owned', 'stores'], []);
    expect(next).toContain('first PSN session');
  });

  it('does not duplicate keys when a manual hide also lacks data', () => {
    const next = computeAutoDisabled(catalog, ['games owned'], ['gamerscore earned']);
    expect(next).toEqual(['stores', 'gamerscore earned', 'first PSN session']);
    expect(new Set(next).size).toBe(next.length);
  });
});
