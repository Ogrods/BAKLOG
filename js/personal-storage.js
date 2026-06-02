import { state, STORAGE_KEY, MANUAL_KEY } from './state.js';
import { personalStore, configurePersonalStore } from './personal-store.js';
import { createMemo } from './memo.js';
import {
  gameKey,
  gameId,
  findGameByKey,
  getSameTitleKeys,
  getTitleKeyIndex,
  normalizeNameForDedup,
} from './game-core.js';
import { savePrefs } from './prefs.js';

const personalMemo = createMemo();

export function bumpPersonalMemo() {
  personalMemo.bump();
}

// === Storage ===
export function loadPersonal() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { return {}; }
}

export function migrateV3() {
  if (state.personal.__migrated_v3) return;
  const next = {};
  for (const [k, v] of Object.entries(state.personal)) {
    if (k === "__migrated_v3") continue;
    if (String(k).includes(":")) next[k] = v;
    else next[`steam:${k}`] = v;
  }
  next.__migrated_v3 = true;
  state.personal = next;
  savePersonal();
}

let _savePersonalTimer = null;
export function savePersonal() {
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = setTimeout(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.personal));
    personalStore.notify();
  }, 250);
}

export function flushSavePersonal() {
  if (!_savePersonalTimer) return;
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = null;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.personal));
  personalStore.notify();
}

window.addEventListener("beforeunload", flushSavePersonal);
window.addEventListener("blur", flushSavePersonal);

export function loadManualGames() {
  try {
    const raw = JSON.parse(localStorage.getItem(MANUAL_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}

export function saveManualGames(list) {
  localStorage.setItem(MANUAL_KEY, JSON.stringify(list));
  personalStore.notify();
}

let manualGames = loadManualGames();

export function addManualGame(g) {
  manualGames = loadManualGames();
  const dupIdx = manualGames.findIndex(m => m.id === g.id && m.store === g.store);
  if (dupIdx >= 0) manualGames[dupIdx] = g;
  else manualGames.push(g);
  saveManualGames(manualGames);
}

export function removeManualGame(store, id) {
  manualGames = loadManualGames().filter(m => !(m.store === store && m.id === id));
  saveManualGames(manualGames);
}

configurePersonalStore({
  getManualGames: loadManualGames,
  setManualGames: (list) => { manualGames = list; },
});

const PERSONAL_DEFAULT = { status: "backlog", notes: "", priority: 0, hltb_override: null, tags: [] };
const PERSONAL_EMPTY = Object.freeze({ status: "backlog", notes: "", priority: 0, hltb_override: null, tags: Object.freeze([]) });

const META_KEYS = new Set(["__migrated_v3", "__tags_canonicalized_v1", "__notes_canonicalized_v1"]);

function isMetaPersonalKey(key) {
  return META_KEYS.has(key) || String(key).startsWith("__");
}

export function getPersonal(g) {
  const key = gameKey(g);
  const ver = window._dataVersion || 0;
  return personalMemo.get(`${key}:${ver}`, () => {
    const found = state.personal[key] || (typeof state.personal[gameId(g)] === "object" ? state.personal[gameId(g)] : null);
    if (!found) return PERSONAL_EMPTY;
    if (found.status == null) found.status = "backlog";
    if (found.notes == null) found.notes = "";
    if (found.priority == null) found.priority = 0;
    if (found.hltb_override === undefined) found.hltb_override = null;
    if (!Array.isArray(found.tags)) found.tags = [];
    return found;
  });
}

export function hasPersonalEntry(g) {
  const key = gameKey(g);
  return !!(state.personal[key] || (typeof state.personal[gameId(g)] === "object" && state.personal[gameId(g)]));
}

// Downstream sync callbacks are registered from app.js to avoid hard cycles
// with filters-ui/picks-ui/dashboard. setPersonal triggers a debounced
// re-render of summary/picks/dashboard via these callbacks.
const downstreamCallbacks = {
  renderSummary: () => {},
  scheduleDashboardRender: () => {},
  renderPicks: () => {},
};

export function configureDownstreamSync({ renderSummary, scheduleDashboardRender, renderPicks }) {
  if (renderSummary) downstreamCallbacks.renderSummary = renderSummary;
  if (scheduleDashboardRender) downstreamCallbacks.scheduleDashboardRender = scheduleDashboardRender;
  if (renderPicks) downstreamCallbacks.renderPicks = renderPicks;
}

let _downstreamSyncTimer = null;
export function scheduleDownstreamSync() {
  clearTimeout(_downstreamSyncTimer);
  _downstreamSyncTimer = setTimeout(() => {
    downstreamCallbacks.renderSummary();
    if (state.activeView === "dashboard") downstreamCallbacks.scheduleDashboardRender();
    else downstreamCallbacks.renderPicks();
  }, 200);
}

export function mergeImportedPersonal(incoming) {
  for (const [key, val] of Object.entries(incoming || {})) {
    if (isMetaPersonalKey(key)) continue;
    if (!val || typeof val !== "object") continue;
    const existing = state.personal[key] || { ...PERSONAL_DEFAULT, tags: [] };
    if (!Array.isArray(existing.tags)) existing.tags = [];
    const incomingTags = Array.isArray(val.tags) ? val.tags : [];
    state.personal[key] = {
      ...existing,
      ...val,
      tags: Array.from(new Set([...(existing.tags || []), ...incomingTags])),
    };
  }
  state.personal.__migrated_v3 = true;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  reconcileNotesAcrossTitles();
}

function noteTextForKey(key) {
  return String(state.personal[key]?.notes ?? "").trim();
}

function pickLongestNoteForKeys(keys) {
  let best = "";
  for (const key of keys) {
    const n = noteTextForKey(key);
    if (n.length > best.length) best = n;
  }
  return best;
}

function mirrorNoteToKeys(keys, note, options) {
  const text = String(note ?? "");
  let changed = false;
  for (const key of keys) {
    if (isMetaPersonalKey(key)) continue;
    if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT, tags: [] };
    if (String(state.personal[key].notes ?? "") === text) continue;
    state.personal[key].notes = text;
    changed = true;
  }
  if (changed) {
    window._dataVersion = (window._dataVersion || 0) + 1;
    personalMemo.bump();
    savePersonal();
    if (!options?.silent) scheduleDownstreamSync();
  }
  return changed;
}

/** Pick the longest non-empty note per title group and mirror to every store copy. */
export function reconcileNotesAcrossTitles() {
  const index = getTitleKeyIndex();
  const processed = new Set();
  let changed = false;

  const applyToGroup = (keys) => {
    const sig = keys.slice().sort().join("|");
    if (processed.has(sig)) return;
    processed.add(sig);
    const canonical = pickLongestNoteForKeys(keys);
    if (mirrorNoteToKeys(keys, canonical, { silent: true })) changed = true;
  };

  for (const keys of index.values()) applyToGroup(keys);

  for (const [key] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    const g = findGameByKey(key);
    if (!g) continue;
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    applyToGroup(index.get(norm) || [key]);
  }

  if (changed) scheduleDownstreamSync();
  return changed;
}

export function canonicalizeNotesAcrossTitles() {
  if (state.personal.__notes_canonicalized_v1) return false;
  const changed = reconcileNotesAcrossTitles();
  state.personal.__notes_canonicalized_v1 = true;
  savePersonal();
  return changed;
}

export function setPersonalByKey(key, field, value, options) {
  if (isMetaPersonalKey(key)) return;
  if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT, tags: [] };
  if (!Array.isArray(state.personal[key].tags)) state.personal[key].tags = [];
  state.personal[key][field] = value;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  if (options?.silent) return;
  scheduleDownstreamSync();
}

export function setPersonal(g, field, value, options) {
  if (field === "notes") {
    mirrorNoteToKeys(getSameTitleKeys(g), value, options);
    return;
  }
  setPersonalByKey(gameKey(g), field, value, options);
}

export function normalizeTag(t) {
  return String(t || "").trim().toLowerCase().replace(/\s+/g, " ").slice(0, 32);
}

function remapTagInPrefs(oldTag, newTag) {
  const filters = state.prefs.tagFilters || [];
  if (!filters.includes(oldTag)) return;
  const next = [...new Set(filters.map(t => (t === oldTag ? newTag : t)))];
  state.prefs.tagFilters = next;
  savePrefs();
}

function removeTagFromPrefs(tag) {
  const filters = state.prefs.tagFilters || [];
  if (!filters.includes(tag)) return;
  state.prefs.tagFilters = filters.filter(t => t !== tag);
  savePrefs();
}

function sortedUniqueTags(tags) {
  return [...new Set(tags)].sort();
}

export function addTagToGame(g, raw) {
  const tag = normalizeTag(raw);
  if (!tag) return false;
  let changed = false;
  for (const key of getSameTitleKeys(g)) {
    const cur = state.personal[key]?.tags || [];
    if (cur.includes(tag)) continue;
    setPersonalByKey(key, "tags", [...cur, tag].sort(), { silent: true });
    changed = true;
  }
  if (changed) scheduleDownstreamSync();
  return changed;
}

export function removeTagFromGame(g, tag) {
  const normalized = normalizeTag(tag);
  if (!normalized) return false;
  let changed = false;
  for (const key of getSameTitleKeys(g)) {
    const cur = state.personal[key]?.tags || [];
    if (!cur.includes(normalized)) continue;
    setPersonalByKey(key, "tags", cur.filter(x => x !== normalized), { silent: true });
    changed = true;
  }
  if (changed) scheduleDownstreamSync();
  return changed;
}

export function renameTagGlobally(oldTag, newTag) {
  const src = normalizeTag(oldTag);
  const dst = normalizeTag(newTag);
  if (!src || !dst || src === dst) return false;
  let changed = false;
  for (const [key, val] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key) || !val || !Array.isArray(val.tags)) continue;
    if (!val.tags.includes(src)) continue;
    const next = sortedUniqueTags(val.tags.map(t => (t === src ? dst : t)));
    setPersonalByKey(key, "tags", next, { silent: true });
    changed = true;
  }
  if (changed) {
    remapTagInPrefs(src, dst);
    scheduleDownstreamSync();
  }
  return changed;
}

export function mergeTagGlobally(srcTag, dstTag) {
  const src = normalizeTag(srcTag);
  const dst = normalizeTag(dstTag);
  if (!src || !dst || src === dst) return false;
  let changed = false;
  for (const [key, val] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key) || !val || !Array.isArray(val.tags)) continue;
    if (!val.tags.includes(src)) continue;
    const next = sortedUniqueTags(val.tags.filter(t => t !== src).concat(dst));
    setPersonalByKey(key, "tags", next, { silent: true });
    changed = true;
  }
  if (changed) {
    remapTagInPrefs(src, dst);
    scheduleDownstreamSync();
  }
  return changed;
}

export function deleteTagGlobally(tag) {
  const normalized = normalizeTag(tag);
  if (!normalized) return false;
  let changed = false;
  for (const [key, val] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key) || !val || !Array.isArray(val.tags)) continue;
    if (!val.tags.includes(normalized)) continue;
    setPersonalByKey(key, "tags", val.tags.filter(t => t !== normalized), { silent: true });
    changed = true;
  }
  if (changed) {
    removeTagFromPrefs(normalized);
    scheduleDownstreamSync();
  }
  return changed;
}

export function canonicalizeTagsAcrossTitles() {
  if (state.personal.__tags_canonicalized_v1) return false;
  const index = getTitleKeyIndex();
  const processed = new Set();
  let changed = false;

  const applyUnionToKeys = (keys) => {
    const sig = keys.slice().sort().join("|");
    if (processed.has(sig)) return;
    processed.add(sig);
    const union = new Set();
    for (const key of keys) {
      const tags = state.personal[key]?.tags;
      if (Array.isArray(tags)) tags.forEach(t => union.add(t));
    }
    if (!union.size) return;
    const sorted = [...union].sort();
    for (const key of keys) {
      const cur = state.personal[key]?.tags || [];
      if (cur.length === sorted.length && sorted.every((t, i) => cur[i] === t)) continue;
      setPersonalByKey(key, "tags", sorted, { silent: true });
      changed = true;
    }
  };

  for (const keys of index.values()) applyUnionToKeys(keys);

  for (const [key] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    const g = findGameByKey(key);
    if (!g) continue;
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    const keys = index.get(norm) || [key];
    applyUnionToKeys(keys);
  }

  state.personal.__tags_canonicalized_v1 = true;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  return changed;
}

export function allPersonalTags() {
  const counts = new Map();
  const seenTitleTag = new Set();

  const countForGame = (g) => {
    const norm = normalizeNameForDedup(g.name);
    if (!norm) return;
    for (const t of getPersonal(g).tags || []) {
      const sig = `${norm}::${t}`;
      if (seenTitleTag.has(sig)) continue;
      seenTitleTag.add(sig);
      counts.set(t, (counts.get(t) || 0) + 1);
    }
  };

  for (const g of [...(state.allGames || []), ...(state.wishlistGames || []), ...(state.itchGames || [])]) {
    countForGame(g);
  }

  for (const [key, val] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key) || !val || !Array.isArray(val.tags)) continue;
    if (findGameByKey(key)) continue;
    for (const t of val.tags) {
      counts.set(t, (counts.get(t) || 0) + 1);
    }
  }

  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/**
 * Personal keys whose game is no longer present in any loaded catalog.
 *
 * Caller MUST ensure the relevant catalogs have already loaded before acting
 * on this (auto-prune is unsafe — a partial library load would flag valid
 * data as orphan). The kebab modal exists so a human triggers cleanup
 * explicitly.
 */
export function findOrphanPersonalKeys() {
  const orphans = [];
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (!rec || typeof rec !== "object") continue;
    if (findGameByKey(key)) continue;
    const status = String(rec.status || "").trim();
    const notes = String(rec.notes || "").trim();
    const tags = Array.isArray(rec.tags) ? rec.tags.filter(Boolean) : [];
    const hltbOverride = rec.hltb_override;
    const hasData = Boolean(
      (status && status !== "backlog") ||
      notes ||
      tags.length > 0 ||
      (hltbOverride != null && hltbOverride !== ""),
    );
    orphans.push({
      key,
      status: status || "backlog",
      notes,
      tags,
      hltbOverride: hltbOverride ?? null,
      hasData,
    });
  }
  orphans.sort((a, b) => {
    if (a.hasData !== b.hasData) return b.hasData - a.hasData;
    return a.key.localeCompare(b.key);
  });
  return orphans;
}

export function countOrphanPersonalKeys() {
  let n = 0;
  for (const key of Object.keys(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (!findGameByKey(key)) n++;
  }
  return n;
}

/**
 * Delete keys from state.personal. The server's rotating backup in
 * data/personal_backups/ is the recoverability story — the next savePersonal
 * triggers a PUT which the server writes atomically with a timestamped backup.
 */
export function prunePersonalKeys(keys) {
  let removed = 0;
  for (const key of keys || []) {
    if (isMetaPersonalKey(key)) continue;
    if (key in state.personal) {
      delete state.personal[key];
      removed++;
    }
  }
  if (removed) {
    window._dataVersion = (window._dataVersion || 0) + 1;
    personalMemo.bump();
    savePersonal();
    scheduleDownstreamSync();
  }
  return removed;
}

export function rebuildPersonalTagsDatalist() {
  const el = document.getElementById("personalTagsList");
  if (!el) return;
  const tags = allPersonalTags().map(([t]) => t);
  el.innerHTML = tags.map(t => `<option value="${String(t).replace(/"/g, "&quot;")}"></option>`).join("");
}
