/**
 * Undated-claim expiry parity:
 *   - admin/claims-workspace.js  isTrustedLiveListing / needsApproveEndDate
 *   - shared/claims_expiry.py    is_trusted_live_listing / needs_approve_end_date
 * Both are driven by tests/fixtures/claims_expiry.json (Python side in
 * tests/test_claims_expiry.py).
 */

import { describe, expect, it } from 'vitest';
import vectors from './fixtures/claims_expiry.json';
import {
  AUTO_HIDE_AGE_MS,
  approveEndDate,
  isStaleAutoClaim,
  isTrustedLiveListing,
  needsApproveEndDate,
} from '../admin/claims-workspace.js';

const NOW = Date.parse(vectors.now);

describe('claims expiry parity', () => {
  for (const c of vectors.cases) {
    it(c.name, () => {
      expect(isTrustedLiveListing(c.item, NOW)).toBe(c.trusted);
      expect(needsApproveEndDate(c.item, NOW)).toBe(c.needs_approve_end_date);
    });
  }

  it('approveEndDate is 14 days out at second precision', () => {
    expect(approveEndDate(Date.parse('2026-10-13T05:00:30.999Z'))).toBe(
      '2026-10-27T05:00:30Z',
    );
  });
});

describe('isStaleAutoClaim with live listings', () => {
  const old = new Date(NOW - AUTO_HIDE_AGE_MS - 86_400_000).toISOString();

  it('keeps an old undated GamerPower row visible while it is still listed', () => {
    const item = {
      source: 'gamerpower',
      first_seen: old,
      last_seen: new Date(NOW - 3_600_000).toISOString(),
    };
    expect(isStaleAutoClaim(item, NOW)).toBe(false);
  });

  it('hides it once GamerPower stops listing it', () => {
    const item = {
      source: 'gamerpower',
      first_seen: old,
      last_seen: new Date(NOW - 3 * 86_400_000).toISOString(),
    };
    expect(isStaleAutoClaim(item, NOW)).toBe(true);
  });
});
