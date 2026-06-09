import { state } from './state.js';

export const TABLE_VIEWS = ['library', 'wishlist', 'itch'];

/** @typedef {{ id: string, label: string, locked?: boolean, defaultVisible: Record<string, boolean> }} TableColumnDef */

/** @type {TableColumnDef[]} */
export const TABLE_COLUMNS = [
  { id: 'select', label: 'Select', locked: true, defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'cover', label: 'Cover', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'game', label: 'Game', locked: true, defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'status', label: 'Status', locked: true, defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'score', label: 'Score', defaultVisible: { library: false, wishlist: false, itch: false } },
  { id: 'played', label: 'Played', defaultVisible: { library: true, wishlist: false, itch: true } },
  { id: 'hltb', label: 'HLTB M/E/C', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'steam', label: 'Steam %', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'mc', label: 'MC', defaultVisible: { library: false, wishlist: false, itch: false } },
  { id: 'price', label: 'Price', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'released', label: 'Released', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'lastplayed', label: 'Last played', defaultVisible: { library: true, wishlist: false, itch: true } },
  { id: 'genres', label: 'Genres', defaultVisible: { library: true, wishlist: true, itch: true } },
  { id: 'notes', label: 'Notes', defaultVisible: { library: true, wishlist: true, itch: true } },
];

function viewKey(view) {
  return TABLE_VIEWS.includes(view) ? view : 'library';
}

function defaultVisibleFor(col, view) {
  return col.defaultVisible[view] ?? col.defaultVisible.library ?? true;
}

export function toggleableColumns() {
  return TABLE_COLUMNS.filter(c => !c.locked);
}

export function ensureColumnsPrefs() {
  if (!state.prefs.columns || typeof state.prefs.columns !== 'object') {
    state.prefs.columns = {};
  }
}

export function isColumnVisible(view, id) {
  const col = TABLE_COLUMNS.find(c => c.id === id);
  if (!col) return true;
  if (col.locked) return true;
  ensureColumnsPrefs();
  const vk = viewKey(view);
  const stored = state.prefs.columns[vk];
  if (stored && typeof stored[id] === 'boolean') return stored[id];
  return defaultVisibleFor(col, vk);
}

export function setColumnVisible(view, id, on) {
  const col = TABLE_COLUMNS.find(c => c.id === id);
  if (!col || col.locked) return;
  ensureColumnsPrefs();
  const vk = viewKey(view);
  if (!state.prefs.columns[vk] || typeof state.prefs.columns[vk] !== 'object') {
    state.prefs.columns[vk] = {};
  }
  state.prefs.columns[vk][id] = !!on;
}

export function resetColumns(view) {
  ensureColumnsPrefs();
  state.prefs.columns[viewKey(view)] = {};
}

export function showAllColumns(view) {
  for (const col of toggleableColumns()) setColumnVisible(view, col.id, true);
}

export function applyColumnVisibility(view) {
  const wrap = document.getElementById('tableWrap');
  if (!wrap) return;
  for (const col of toggleableColumns()) {
    wrap.classList.toggle(`table-hide-${col.id}`, !isColumnVisible(view, col.id));
  }
}

/** Migrate legacy showScoreColumn / showMetacriticColumn prefs into per-view maps. */
export function migrateColumnPrefs(merged) {
  if (!merged.columns || typeof merged.columns !== 'object') {
    merged.columns = {};
  }
  const hadScore = merged.showScoreColumn;
  const hadMc = merged.showMetacriticColumn;
  if (hadScore !== undefined || hadMc !== undefined) {
    for (const view of TABLE_VIEWS) {
      if (!merged.columns[view] || typeof merged.columns[view] !== 'object') {
        merged.columns[view] = {};
      }
      if (hadScore !== undefined && merged.columns[view].score === undefined) {
        merged.columns[view].score = !!hadScore;
      }
      if (hadMc !== undefined && merged.columns[view].mc === undefined) {
        merged.columns[view].mc = !!hadMc;
      }
    }
  }
  delete merged.showScoreColumn;
  delete merged.showMetacriticColumn;
}
