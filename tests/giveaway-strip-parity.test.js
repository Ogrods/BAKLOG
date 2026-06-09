/**
 * Cross-implementation parity for giveaway-title stripping.
 *
 * The same regex chain lives in three places and must stay in sync:
 *   - js/claim-card.js            stripClaimTitleDecorations (re-exported by claimable.js)
 *   - admin/claims-workspace.js  stripClaimTitleDecorations
 *   - shared/steam_match.py      strip_giveaway_decorations  (checked in pytest)
 *
 * All three are driven by tests/fixtures/giveaway_title_strip.json so a change
 * to one without the others fails here (JS) or in test_steam_match.py (Python).
 */

import { describe, expect, it } from 'vitest';
import vectors from './fixtures/giveaway_title_strip.json';
import { stripClaimTitleDecorations as stripApp } from '../js/claimable.js';
import { stripClaimTitleDecorations as stripAdmin, coverLookupKey } from '../admin/claims-workspace.js';

describe('giveaway title strip parity (JS)', () => {
  for (const { input, expected } of vectors) {
    it(`app strips ${JSON.stringify(input)} -> ${JSON.stringify(expected)}`, () => {
      expect(stripApp(input)).toBe(expected);
    });
    it(`admin strips ${JSON.stringify(input)} identically`, () => {
      expect(stripAdmin(input)).toBe(stripApp(input));
    });
  }
});

describe('coverLookupKey is built on the shared strip', () => {
  it('catches in-game-item and chapter decorations the old subset missed', () => {
    expect(coverLookupKey('Warframe in game items')).toBe('warframe');
    expect(coverLookupKey('Saga - Chapters 1,2,3')).toBe('saga');
  });
});
