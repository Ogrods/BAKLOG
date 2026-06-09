/**
 * Cross-implementation parity for ITAD blurb cleanup.
 * Sync pair: js/claim-card.js sanitizeBlurb ↔ build_free_claims._clean_blurb
 */

import { describe, expect, it } from 'vitest';
import vectors from './fixtures/blurb_sanitize.json';
import { sanitizeBlurb } from '../js/claim-card.js';

describe('blurb sanitize parity (JS)', () => {
  for (const { input, expected } of vectors) {
    it(`strips ${JSON.stringify(input).slice(0, 40)}…`, () => {
      expect(sanitizeBlurb(input)).toBe(expected);
    });
  }
});
