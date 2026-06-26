/**
 * Cross-implementation parity for library noise rules.
 * Sync pair: js/library-noise.js ↔ shared/library_noise.py
 */

import { describe, expect, it } from 'vitest';
import vectors from './fixtures/library_noise.json';
import { shouldAutoHideByTitle, editionBaseKey, shouldAutoHidePsnTitle, shouldAutoHideGogTitle, shouldAutoHideNintendoTitle } from '../js/library-noise.js';

describe('library noise parity (JS)', () => {
  for (const row of vectors) {
    if (Object.prototype.hasOwnProperty.call(row, 'should_auto_hide')) {
      it(`shouldAutoHideByTitle ${JSON.stringify(row.title)}`, () => {
        expect(shouldAutoHideByTitle(row.title)).toBe(row.should_auto_hide);
      });
    }
    if (Object.prototype.hasOwnProperty.call(row, 'should_auto_hide_psn')) {
      it(`shouldAutoHidePsnTitle ${JSON.stringify(row.title)}`, () => {
        expect(shouldAutoHidePsnTitle(row.title)).toBe(row.should_auto_hide_psn);
      });
    }
    if (Object.prototype.hasOwnProperty.call(row, 'should_auto_hide_gog')) {
      it(`shouldAutoHideGogTitle ${JSON.stringify(row.title)}`, () => {
        expect(shouldAutoHideGogTitle(row.title)).toBe(row.should_auto_hide_gog);
      });
    }
    if (Object.prototype.hasOwnProperty.call(row, 'should_auto_hide_nintendo')) {
      it(`shouldAutoHideNintendoTitle ${JSON.stringify(row.title)}`, () => {
        expect(shouldAutoHideNintendoTitle(row.title)).toBe(row.should_auto_hide_nintendo);
      });
    }
    if (row.edition_base_key) {
      it(`editionBaseKey ${JSON.stringify(row.title)}`, () => {
        expect(editionBaseKey(row.title)).toBe(row.edition_base_key);
      });
    }
  }
});
