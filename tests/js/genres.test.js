import { describe, expect, it } from 'vitest';
import { gameGenresCanonical, isPlatformToken } from '../../js/genres.js';

describe('genres', () => {
  it('filters itch upload types', () => {
    expect(isPlatformToken('html')).toBe(true);
    expect(isPlatformToken('default')).toBe(true);
    expect(isPlatformToken('Platformer')).toBe(false);
  });

  it('canonicalizes without platform tokens', () => {
    const g = { genres: ['Action', 'html', 'default', 'Platformer'] };
    expect(gameGenresCanonical(g)).toEqual(['Action', 'Platformer']);
  });
});
