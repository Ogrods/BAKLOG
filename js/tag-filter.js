/**
 * Pure personal-tag filter logic. Safe to import from the table-query worker —
 * no DOM, no state, no `window` reference.
 */

export function passesTagFilterFromPrefs(prefs, gameTags) {
  const tagFilters = prefs?.tagFilters || [];
  if (!tagFilters.length) return true;
  const tags = gameTags || [];
  if (prefs?.tagFilterMode === 'AND') return tagFilters.every(t => tags.includes(t));
  return tagFilters.some(t => tags.includes(t));
}
