/**
 * Cross-implementation parity for library noise rules.
 * Sync pair: js/library-noise.js ↔ shared/library_noise.py
 */

import { describe, expect, it } from 'vitest';
import vectors from './fixtures/library_noise.json';
import { shouldAutoHideByTitle, editionBaseKey } from '../js/library-noise.js';

describe('library noise parity (JS)', () => {
  for (const row of vectors) {
    if (Object.prototype.hasOwnProperty.call(row, 'should_auto_hide')) {
      it(`shouldAutoHideByTitle ${JSON.stringify(row.title)}`, () => {
        expect(shouldAutoHideByTitle(row.title)).toBe(row.should_auto_hide);
      });
    }
    if (row.edition_base_key) {
      it(`editionBaseKey ${JSON.stringify(row.title)}`, () => {
        expect(editionBaseKey(row.title)).toBe(row.edition_base_key);
      });
    }
  }
});
