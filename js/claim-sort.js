/**
 * Canonical sort helpers for free-claims rows.
 * Shared by the live app (js/claim-card.js sortClaims) and the admin Claims
 * workspace table (admin/claims-workspace.js re-exports).
 *
 * Sync pair: SORT_FNS / sortClaimsItems ↔ admin/claims-workspace.js re-export
 */

export function parseEndsAtMs(value) {
  if (!value) return null;
  const t = Date.parse(String(value));
  return Number.isFinite(t) ? t : null;
}

const SORT_FNS = {
  newest: (a, b) => {
    const ta = parseEndsAtMs(a.first_seen);
    const tb = parseEndsAtMs(b.first_seen);
    if (ta != null && tb != null) {
      if (ta !== tb) return tb - ta;
      // Same fetch batch: preserve incoming (feed) order so a stable sort keeps
      // sources grouped. id-desc here buried epic/gamerpower under itad-*.
      return 0;
    }
    if (ta != null) return -1;
    if (tb != null) return 1;
    // Neither has a first_seen stamp: fall back to id descending.
    return String(b.id || '').localeCompare(String(a.id || ''));
  },
  ends_soon: (a, b) => {
    const ta = parseEndsAtMs(a.ends_at);
    const tb = parseEndsAtMs(b.ends_at);
    if (ta == null && tb == null) return 0;
    if (ta == null) return 1;
    if (tb == null) return -1;
    return ta - tb;
  },
  title: (a, b) => String(a.title || '').localeCompare(String(b.title || ''), undefined, { sensitivity: 'base' }),
  store: (a, b) => String(a.store || '').localeCompare(String(b.store || '')),
};

export function sortClaimsItems(items, sortKey = 'newest') {
  const fn = SORT_FNS[sortKey] || SORT_FNS.newest;
  return [...items].sort(fn);
}
