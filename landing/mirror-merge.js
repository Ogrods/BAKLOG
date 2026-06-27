/** Pure helpers for the hosted read-only cloud mirror viewer (M3). */

export const STATUS_LABELS = {
  backlog: 'Backlog',
  next: 'Next up',
  playing: 'Playing',
  unfinished: 'Unfinished',
  live: 'Live service',
  finished: 'Finished',
  skip: 'Skip',
};

export const STORE_LABELS = {
  steam: 'Steam',
  gog: 'GOG',
  psn: 'PSN',
  epic: 'Epic',
  epic_mobile: 'Epic Mobile',
  amazon: 'Amazon',
  xbox: 'Xbox',
  battlenet: 'Battle.net',
  ubisoft: 'Ubisoft',
  nintendo: 'Nintendo',
  humble: 'Humble',
  ea: 'EA App',
  itch: 'itch.io',
  indiegala: 'IndieGala',
  other: 'Other',
  manual: 'Manual',
};

const CATALOG_ARTIFACT_RE = /^games_(?!wishlist_)([a-z0-9_]+)\.json$/;

/** @param {string} path */
export function storeFromCatalogArtifact(path) {
  const m = String(path || '').trim().match(CATALOG_ARTIFACT_RE);
  return m ? m[1] : null;
}

/** @param {{ path?: string }[]} artifacts */
export function catalogArtifactPaths(artifacts) {
  const paths = (artifacts || [])
    .map((row) => String(row?.path || '').trim())
    .filter(Boolean);
  return paths
    .filter((path) => storeFromCatalogArtifact(path))
    .sort((a, b) => storeRank(storeFromCatalogArtifact(a)) - storeRank(storeFromCatalogArtifact(b)) || a.localeCompare(b));
}

function storeRank(store) {
  const order = Object.keys(STORE_LABELS);
  const idx = order.indexOf(store || '');
  return idx === -1 ? order.length : idx;
}

/** @param {Record<string, unknown>} g */
export function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  const store = g.store || 'steam';
  const id =
    g.id ??
    g.appid ??
    g.gog_id ??
    g.psn_id ??
    g.epic_catalog_id ??
    g.amazon_id ??
    g.application_id ??
    g.nintendo_id ??
    g.itch_id ??
    g.xbox_title_id ??
    g.battlenet_id ??
    g.ubisoft_id ??
    g.humble_id ??
    g.ea_id;
  return { ...g, store, id };
}

/** @param {Record<string, unknown>} g */
export function gameKey(g) {
  const ng = normalizeGame(g);
  return `${ng.store}:${ng.id}`;
}

/** @param {Record<string, unknown>} g */
export function playtimeHoursFromGame(g) {
  if (g.playtime_forever != null && Number.isFinite(Number(g.playtime_forever))) {
    return Math.round((Number(g.playtime_forever) / 60) * 10) / 10;
  }
  if (g.playtime_hours != null && Number.isFinite(Number(g.playtime_hours))) {
    return Math.round(Number(g.playtime_hours) * 10) / 10;
  }
  return null;
}

function personalMap(personalDoc) {
  if (!personalDoc || typeof personalDoc !== 'object') return {};
  if (personalDoc.personal && typeof personalDoc.personal === 'object') return personalDoc.personal;
  return personalDoc;
}

/**
 * @param {{ path: string, doc: unknown }[]} catalogEntries
 * @param {unknown} personalDoc
 * @param {{ includeHidden?: boolean }} [options]
 */
export function mergeMirrorLibrary(catalogEntries, personalDoc, options = {}) {
  const personal = personalMap(personalDoc);
  const rows = [];
  for (const entry of catalogEntries || []) {
    const store = storeFromCatalogArtifact(entry.path);
    if (!store) continue;
    const doc = entry.doc && typeof entry.doc === 'object' ? entry.doc : {};
    const games = Array.isArray(doc.games) ? doc.games : [];
    for (const raw of games) {
      const g = normalizeGame({ ...raw, store });
      const key = gameKey(g);
      const rec = personal[key] && typeof personal[key] === 'object' ? personal[key] : {};
      const hidden = rec.hidden === true;
      if (hidden && !options.includeHidden) continue;
      const status = String(rec.status || g.status || 'backlog');
      rows.push({
        key,
        store,
        storeLabel: STORE_LABELS[store] || store,
        title: String(g.name || 'Unknown'),
        status,
        statusLabel: STATUS_LABELS[status] || status,
        playtimeHours: playtimeHoursFromGame(g),
        hltbMain: g.hltb_main_hours ?? g.hltb_main ?? null,
        notes: String(rec.notes || ''),
        hidden,
      });
    }
  }
  rows.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }) || a.store.localeCompare(b.store));
  return rows;
}

/**
 * @param {ReturnType<typeof mergeMirrorLibrary>} rows
 * @param {{ search?: string, status?: string, store?: string, showHidden?: boolean }} filters
 */
export function filterMirrorRows(rows, filters = {}) {
  const search = String(filters.search || '').trim().toLowerCase();
  const status = String(filters.status || '').trim();
  const store = String(filters.store || '').trim();
  const showHidden = filters.showHidden === true;
  return (rows || []).filter((row) => {
    if (!showHidden && row.hidden) return false;
    if (status && row.status !== status) return false;
    if (store && row.store !== store) return false;
    if (search) {
      const hay = `${row.title} ${row.notes} ${row.storeLabel}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
}

/**
 * @param {ReturnType<typeof mergeMirrorLibrary>} rows
 * @param {{ column?: string, direction?: 'asc'|'desc' }} sort
 */
export function sortMirrorRows(rows, sort = {}) {
  const column = sort.column || 'title';
  const dir = sort.direction === 'desc' ? -1 : 1;
  const list = [...(rows || [])];
  list.sort((a, b) => {
    let va;
    let vb;
    switch (column) {
      case 'store':
        va = a.storeLabel;
        vb = b.storeLabel;
        break;
      case 'status':
        va = a.statusLabel;
        vb = b.statusLabel;
        break;
      case 'playtime':
        va = a.playtimeHours ?? -1;
        vb = b.playtimeHours ?? -1;
        break;
      case 'hltb':
        va = a.hltbMain ?? -1;
        vb = b.hltbMain ?? -1;
        break;
      default:
        va = a.title;
        vb = b.title;
    }
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return a.key.localeCompare(b.key) * dir;
  });
  return list;
}

/** @param {ReturnType<typeof mergeMirrorLibrary>} rows */
export function summarizeMirrorRows(rows) {
  const list = rows || [];
  const stores = new Set(list.map((r) => r.store));
  const statuses = {};
  for (const row of list) {
    statuses[row.status] = (statuses[row.status] || 0) + 1;
  }
  return {
    total: list.length,
    stores: [...stores].sort((a, b) => storeRank(a) - storeRank(b)),
    statuses,
  };
}
