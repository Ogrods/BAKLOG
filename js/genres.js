import { GENRE_ALIASES } from './state.js';

export const NON_GENRE_TOKENS = new Set([
  'ps3', 'ps4', 'ps5', 'psp', 'ps vita', 'psvita', 'vita',
  'xbox', 'xbox 360', 'xbox one', 'xbox series x', 'xbox series s', 'xbox series x|s', 'xbox series x/s', 'xbox series',
  'nintendo switch', 'switch', 'wii', 'wii u', 'ds', '3ds', 'nintendo ds', 'nintendo 3ds',
  'pc', 'windows', 'mac', 'macos', 'osx', 'linux', 'steamos',
  'ios', 'android', 'browser', 'stadia', 'google stadia',
  'default', 'html', 'flash', 'unity', 'java', 'mobile', 'physical',
]);

export function isPlatformToken(name) {
  return NON_GENRE_TOKENS.has(String(name || '').trim().toLowerCase());
}

export function aliasCanonicalGenre(name) {
  return GENRE_ALIASES[name] || name;
}

export function gameGenresCanonical(g) {
  return [...new Set((g.genres || []).filter(x => !isPlatformToken(x)).map(aliasCanonicalGenre))];
}

export function gameMatchesGenreFilters(g, genres, genreMode) {
  const gameGenres = gameGenresCanonical(g);
  if (!genres.length) return true;
  if (genreMode === 'AND') return genres.every(x => gameGenres.includes(x));
  return genres.some(x => gameGenres.includes(x));
}
