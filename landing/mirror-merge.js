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
const STEAM_HEADER_CDN = 'https://cdn.akamai.steamstatic.com/steam/apps';

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

/** @param {unknown} url */
export function sanitizeMirrorCoverUrl(url) {
  if (!url) return '';
  let u = String(url).trim();
  if (!u) return '';
  u = u.replace('://images-eds.xboxlive.com/', '://images-eds-ssl.xboxlive.com/');
  if (u.includes('${size}') && /cdn\.nintendo\.net/i.test(u)) {
    u = u.replace(/\$\{size\}/g, '256');
  }
  if (!/^https?:\/\//i.test(u)) return '';
  return u;
}

/**
 * Prefer library_image, then header_image, then Steam header CDN.
 * @param {Record<string, unknown>} g
 */
export function mirrorCoverUrlFor(g) {
  const lib = sanitizeMirrorCoverUrl(g?.library_image);
  if (lib) return lib;
  const header = sanitizeMirrorCoverUrl(g?.header_image);
  if (header) return header;
  const store = String(g?.store || '').toLowerCase();
  const id = g?.id;
  if (store === 'steam' && id != null && String(id).trim() !== '' && /^\d+$/.test(String(id))) {
    return `${STEAM_HEADER_CDN}/${id}/header.jpg`;
  }
  return '';
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

function finiteOrNull(value) {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** @param {unknown} raw */
function genresFromGame(raw) {
  if (Array.isArray(raw)) {
    return raw
      .map((g) => (typeof g === 'string' ? g : g?.description || g?.name || ''))
      .map((s) => String(s).trim())
      .filter(Boolean)
      .slice(0, 2);
  }
  if (typeof raw === 'string' && raw.trim()) {
    return raw
      .split(/[,;/|]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 2);
  }
  return [];
}

/** @param {Record<string, unknown>} g */
function platformsFromGame(g) {
  const raw = g.platforms ?? g.platform ?? g.psn_platforms;
  if (Array.isArray(raw)) {
    return raw
      .map((p) => String(p || '').trim())
      .filter(Boolean)
      .slice(0, 4)
      .join(', ');
  }
  const s = String(raw || '').trim();
  return s || '';
}

/** @param {unknown} value */
function dateLabel(value) {
  if (value == null || value === '') return '';
  if (typeof value === 'number' && Number.isFinite(value)) {
    // Steam rtime_last_played is unix seconds.
    const ms = value > 1e12 ? value : value * 1000;
    const d = new Date(ms);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }
  }
  const s = String(value).trim();
  if (!s) return '';
  const parsed = Date.parse(s);
  if (!Number.isNaN(parsed)) {
    return new Date(parsed).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }
  return s;
}

/**
 * Compact ITAD label from a by_key entry (`price_str`, optional cut).
 * @param {Record<string, unknown> | null | undefined} entry
 */
export function formatItadPriceLabel(entry) {
  if (!entry || typeof entry !== 'object') return '';
  const cut = finiteOrNull(entry.cut);
  const priceStr = String(entry.price_str || '').trim();
  if (priceStr && cut != null && cut > 0) return `${priceStr} (-${Math.round(cut)}%)`;
  if (priceStr) return priceStr;
  const price = finiteOrNull(entry.price);
  if (price == null) return '';
  const currency = String(entry.currency || 'USD').trim() || 'USD';
  const base = `${currency} ${price % 1 === 0 ? price : price.toFixed(2)}`;
  if (cut != null && cut > 0) return `${base} (-${Math.round(cut)}%)`;
  return base;
}

/**
 * Attach `priceLabel` from mirrored `itad_prices.json` (`by_key`).
 * @param {ReturnType<typeof mergeMirrorLibrary>} rows
 * @param {unknown} itadDoc
 */
export function mergeItadPrices(rows, itadDoc) {
  const byKey =
    itadDoc && typeof itadDoc === 'object' && itadDoc.by_key && typeof itadDoc.by_key === 'object'
      ? itadDoc.by_key
      : {};
  return (rows || []).map((row) => {
    const entry = byKey[row.key];
    const priceLabel = formatItadPriceLabel(entry && typeof entry === 'object' ? entry : null);
    return priceLabel ? { ...row, priceLabel } : { ...row, priceLabel: row.priceLabel || '' };
  });
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
      const steamPercent =
        finiteOrNull(g.steam_percent) ??
        finiteOrNull(g.review_percent) ??
        finiteOrNull(g.steam_rating) ??
        finiteOrNull(g.rating);
      const metacritic = finiteOrNull(g.metacritic) ?? finiteOrNull(g.metacritic_score);
      rows.push({
        key,
        store,
        storeLabel: STORE_LABELS[store] || store,
        title: String(g.name || 'Unknown'),
        status,
        statusLabel: STATUS_LABELS[status] || status,
        playtimeHours: playtimeHoursFromGame(g),
        hltbMain: finiteOrNull(g.hltb_main_hours ?? g.hltb_main),
        hltbExtra: finiteOrNull(g.hltb_extra_hours ?? g.hltb_extra),
        hltbCompletionist: finiteOrNull(g.hltb_completionist_hours ?? g.hltb_completionist),
        notes: String(rec.notes || ''),
        hidden,
        coverUrl: mirrorCoverUrlFor(g),
        steamPercent,
        metacritic,
        released: dateLabel(g.release_date ?? g.released ?? g.release),
        lastPlayed: dateLabel(g.last_played ?? g.rtime_last_played ?? g.lastplayed),
        genres: genresFromGame(g.genres ?? g.genre),
        platforms: platformsFromGame(g),
        priceLabel: '',
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
      const genreHay = Array.isArray(row.genres) ? row.genres.join(' ') : '';
      const hay = `${row.title} ${row.notes} ${row.storeLabel} ${genreHay} ${row.platforms || ''}`.toLowerCase();
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
      case 'steam':
        va = a.steamPercent ?? -1;
        vb = b.steamPercent ?? -1;
        break;
      case 'metacritic':
        va = a.metacritic ?? -1;
        vb = b.metacritic ?? -1;
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
