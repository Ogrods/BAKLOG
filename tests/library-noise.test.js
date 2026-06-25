import { describe, expect, it } from 'vitest';
import {
  editionBaseKey,
  isNintendoNoiseRow,
  shouldAutoHideByTitle,
  shouldAutoHideLibraryRow,
} from '../js/library-noise.js';

describe('shouldAutoHideByTitle', () => {
  it('flags streaming apps and Nintendo extras', () => {
    expect(shouldAutoHideByTitle('YouTube')).toBe(true);
    expect(shouldAutoHideByTitle('Hulu')).toBe(true);
    expect(shouldAutoHideByTitle('Sonic Digital Art Book')).toBe(true);
    expect(shouldAutoHideByTitle('Persona 5 Royal Picaro Set')).toBe(true);
  });

  it('keeps real games visible', () => {
    expect(shouldAutoHideByTitle('Wallpaper Engine')).toBe(false);
    expect(shouldAutoHideByTitle('Costume Quest')).toBe(false);
    expect(shouldAutoHideByTitle('Hades')).toBe(false);
    expect(shouldAutoHideByTitle('ARK: Ragnarok')).toBe(false);
  });
});

describe('editionBaseKey', () => {
  it('groups edition SKUs for within-store dedupe', () => {
    expect(editionBaseKey('Game Digital Deluxe Edition')).toBe(editionBaseKey('Game'));
  });
});

describe('isNintendoNoiseRow', () => {
  it('treats DLC without app as noise', () => {
    expect(isNintendoNoiseRow({ name: 'Bonus Pack', tags: ['dlc'] })).toBe(true);
  });

  it('keeps DLC with application metadata', () => {
    expect(
      isNintendoNoiseRow({
        name: 'Expansion',
        tags: ['dlc'],
        has_nx_application: true,
      }),
    ).toBe(false);
  });
});

describe('shouldAutoHideLibraryRow', () => {
  it('applies store-specific guards', () => {
    expect(shouldAutoHideLibraryRow({ store: 'steam', name: 'YouTube' })).toBe(true);
    expect(
      shouldAutoHideLibraryRow(
        { store: 'itch', name: 'My Tool' },
        { itchIsGameFn: () => false },
      ),
    ).toBe(true);
  });
});
