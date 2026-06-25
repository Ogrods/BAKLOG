import { state } from './state.js';
import { findGameByKey } from './game-core.js';
import { savePrefs } from './prefs.js';

export const CUSTOM_LIST_COUNT = 3;
export const CUSTOM_LIST_MAX_KEYS = 9999;
export const CUSTOM_LIST_NAME_MAX = 24;
/** Drawer chip label cap (full name stays in title). */
export const CUSTOM_LIST_FILTER_LABEL_MAX = 18;

export function defaultCustomLists() {
  return [
    { name: 'List 1', keys: [] },
    { name: 'List 2', keys: [] },
    { name: 'List 3', keys: [] },
  ];
}

export function defaultListName(index) {
  return `List ${index + 1}`;
}

/** Normalize prefs.customLists to exactly 3 slots. */
export function migrateCustomLists(prefs) {
  const raw = Array.isArray(prefs?.customLists) ? prefs.customLists : [];
  const lists = [];
  for (let i = 0; i < CUSTOM_LIST_COUNT; i++) {
    const src = raw[i] && typeof raw[i] === 'object' ? raw[i] : {};
    const name = sanitizeListName(src.name, i);
    const keys = Array.isArray(src.keys)
      ? src.keys.filter(k => typeof k === 'string' && k.trim())
      : [];
    lists.push({ name, keys: keys.slice(0, CUSTOM_LIST_MAX_KEYS) });
  }
  return lists;
}

export function sanitizeListName(name, index = 0) {
  const trimmed = String(name ?? '').trim().slice(0, CUSTOM_LIST_NAME_MAX);
  return trimmed || defaultListName(index);
}

export function getCustomLists() {
  state.prefs.customLists = migrateCustomLists(state.prefs);
  return state.prefs.customLists;
}

export function customListTabId(index) {
  return `customList${index}`;
}

export function parseCustomListTabId(tab) {
  const m = /^customList([0-2])$/.exec(tab || '');
  return m ? Number(m[1]) : -1;
}

export function isCustomListTab(tab) {
  return parseCustomListTabId(tab) >= 0;
}

/** Library picks tab with fallback when a custom tab is hidden (empty + default name). */
export function resolveLibraryPicksTab(prefTab, libraryPicksTab) {
  const primary = prefTab || libraryPicksTab || 'topRated';
  if (!isCustomListTab(primary)) return primary;
  const lists = getCustomLists();
  const idx = parseCustomListTabId(primary);
  if (shouldShowCustomListTab(lists[idx], idx)) return primary;
  const fallback = libraryPicksTab || 'topRated';
  if (!isCustomListTab(fallback)) return fallback;
  const fidx = parseCustomListTabId(fallback);
  return shouldShowCustomListTab(lists[fidx], fidx) ? fallback : 'topRated';
}

export function listHasResolvableGame(list) {
  return (list?.keys || []).some(k => !!findGameByKey(k));
}

export function isListRenamed(list, index) {
  const name = String(list?.name ?? '').trim();
  return name !== '' && name !== defaultListName(index);
}

/** Show tab when list has games or user renamed it from default. */
export function shouldShowCustomListTab(list, index) {
  return listHasResolvableGame(list) || isListRenamed(list, index);
}

export function resolveCustomListGames(list) {
  const out = [];
  for (const key of list?.keys || []) {
    const g = findGameByKey(key);
    if (g) out.push(g);
  }
  return out;
}

export function countOrphanKeys(list) {
  return (list?.keys || []).filter(k => !findGameByKey(k)).length;
}

export function pruneOrphanKeys(listIndex) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return 0;
  const before = list.keys.length;
  list.keys = list.keys.filter(k => !!findGameByKey(k));
  const removed = before - list.keys.length;
  if (removed) savePrefs();
  return removed;
}

export function pruneAllOrphanKeys() {
  let total = 0;
  for (let i = 0; i < CUSTOM_LIST_COUNT; i++) total += pruneOrphanKeys(i);
  return total;
}

export function renameCustomList(listIndex, name) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return;
  list.name = sanitizeListName(name, listIndex);
  savePrefs();
}

export function clearCustomList(listIndex) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list || !list.keys.length) return;
  list.keys = [];
  savePrefs();
}

export function removeFromCustomList(listIndex, key) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return false;
  const idx = list.keys.indexOf(key);
  if (idx < 0) return false;
  list.keys.splice(idx, 1);
  savePrefs();
  return true;
}

export function moveCustomListKey(listIndex, key, delta) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return false;
  const idx = list.keys.indexOf(key);
  if (idx < 0) return false;
  const next = idx + delta;
  if (next < 0 || next >= list.keys.length) return false;
  return moveCustomListKeyToIndex(listIndex, key, next);
}

/** Move one key to an absolute index in the list (0-based). */
export function moveCustomListKeyToIndex(listIndex, key, toIndex) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return false;
  const fromIdx = list.keys.indexOf(key);
  if (fromIdx < 0) return false;
  const target = Math.max(0, Math.min(toIndex, list.keys.length - 1));
  if (fromIdx === target) return false;
  const [item] = list.keys.splice(fromIdx, 1);
  list.keys.splice(target, 0, item);
  savePrefs();
  return true;
}

/**
 * Append keys to a list (skips dupes). Returns { added, skippedFull }.
 */
export function addKeysToCustomList(listIndex, keys) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return { added: 0, skippedFull: 0 };
  const have = new Set(list.keys);
  let added = 0;
  let skippedFull = 0;
  for (const key of keys) {
    if (!key || have.has(key)) continue;
    if (list.keys.length >= CUSTOM_LIST_MAX_KEYS) {
      skippedFull++;
      continue;
    }
    list.keys.push(key);
    have.add(key);
    added++;
  }
  if (added) savePrefs();
  return { added, skippedFull };
}

export function removeKeysFromCustomList(listIndex, keys) {
  const lists = getCustomLists();
  const list = lists[listIndex];
  if (!list) return 0;
  const drop = new Set(keys);
  const before = list.keys.length;
  list.keys = list.keys.filter(k => !drop.has(k));
  const removed = before - list.keys.length;
  if (removed) savePrefs();
  return removed;
}

function truncateTabLabel(name, max = 14) {
  const s = String(name || '').trim();
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

export function formatCustomListFilterLabel(name, max = CUSTOM_LIST_FILTER_LABEL_MAX) {
  return truncateTabLabel(name, max);
}

/** Persisted prefs.customListFilter: null = off, 0|1|2 = list slot. */
export function normalizeCustomListFilter(value) {
  if (value == null || value === '') return null;
  const idx = Number(value);
  if (!Number.isInteger(idx) || idx < 0 || idx >= CUSTOM_LIST_COUNT) return null;
  return idx;
}

/** Keys for the active library list filter, or null when off. */
export function getCustomListFilterKeySet(prefs) {
  const idx = normalizeCustomListFilter(prefs?.customListFilter);
  if (idx == null) return null;
  const lists = migrateCustomLists(prefs);
  const keys = lists[idx]?.keys;
  if (!keys?.length) return new Set();
  return new Set(keys);
}

/** Refresh custom Picks tab labels and visibility in the tab bar. */
export function renderCustomPickTabs() {
  const lists = getCustomLists();
  const pickView = state.activeView === 'wishlist' ? 'wishlist' : state.activeView === 'itch' ? 'itch' : 'library';
  for (let i = 0; i < CUSTOM_LIST_COUNT; i++) {
    const btn = document.querySelector(`.pick-tab[data-tab="customList${i}"]`);
    if (!btn) continue;
    const list = lists[i];
    const resolved = (list?.keys || []).filter(k => !!findGameByKey(k)).length;
    const visible = pickView === 'library' && shouldShowCustomListTab(list, i);
    btn.classList.toggle('hidden', !visible);
    const label = truncateTabLabel(list?.name || defaultListName(i));
    btn.textContent = label;
    btn.title = list?.name ? `${list.name} (${resolved} games)` : defaultListName(i);
  }
  const sep = document.querySelector('.pick-tab-sep-custom');
  if (sep) {
    const anyVisible = pickView === 'library' && lists.some((list, i) => shouldShowCustomListTab(list, i));
    sep.classList.toggle('hidden', !anyVisible);
  }
}
