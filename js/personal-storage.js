import { state, STORAGE_KEY, MANUAL_KEY } from './state.js';
import { profileScopedStorageKey } from './profiles.js';

export function personalStorageKey() {
  return profileScopedStorageKey(STORAGE_KEY);
}

export function manualStorageKey() {
  return profileScopedStorageKey(MANUAL_KEY);
}
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
import { PRE_HIDDEN_KEYS, getPreHiddenFallback } from './hidden-defaults.js';

const personalMemo = createMemo();

export function bumpPersonalMemo() {
  personalMemo.bump();
}

// === Storage ===
export function loadPersonal() {
  try { return JSON.parse(localStorage.getItem(personalStorageKey()) || "{}"); } catch { return {}; }
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

/** One-shot: strip legacy `tags` field and tag filter prefs. Idempotent via __tags_removed_v1. */
export function stripLegacyTags() {
  if (state.personal.__tags_removed_v1) return false;
  let changed = false;
  for (const val of Object.values(state.personal)) {
    if (!val || typeof val !== "object") continue;
    if ("tags" in val) {
      delete val.tags;
      changed = true;
    }
  }
  if ("__tags_canonicalized_v1" in state.personal) {
    delete state.personal.__tags_canonicalized_v1;
    changed = true;
  }
  state.personal.__tags_removed_v1 = true;
  if (state.prefs) {
    if ("tagFilters" in state.prefs) { delete state.prefs.tagFilters; changed = true; }
    if ("tagFilterMode" in state.prefs) { delete state.prefs.tagFilterMode; changed = true; }
  }
  if (changed) savePersonal();
  return changed;
}

let _savePersonalTimer = null;
export function savePersonal() {
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = setTimeout(() => {
    localStorage.setItem(personalStorageKey(), JSON.stringify(state.personal));
    personalStore.notify();
  }, 250);
}

export function flushSavePersonal() {
  if (!_savePersonalTimer) return;
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = null;
  localStorage.setItem(personalStorageKey(), JSON.stringify(state.personal));
  personalStore.notify();
}

window.addEventListener("beforeunload", flushSavePersonal);
window.addEventListener("blur", flushSavePersonal);

export function loadManualGames() {
  try {
    const raw = JSON.parse(localStorage.getItem(manualStorageKey()) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}

export function saveManualGames(list) {
  localStorage.setItem(manualStorageKey(), JSON.stringify(list));
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

const PERSONAL_DEFAULT = { status: "backlog", notes: "", priority: 0, hltb_override: null, hidden: false, started_at: null, finished_at: null };
const PERSONAL_EMPTY = Object.freeze({ status: "backlog", notes: "", priority: 0, hltb_override: null, hidden: false, started_at: null, finished_at: null });

const META_KEYS = new Set([
  "__migrated_v3",
  "__notes_canonicalized_v1",
  "__tags_removed_v1",
  "__pre_hidden_v1_seeded",
  "__hidden_mirrored_v1",
  "__hidden_title_norms_v1",
  "__hidden_title_norms_migrated_v1",
]);

function isMetaPersonalKey(key) {
  return META_KEYS.has(key) || String(key).startsWith("__");
}

function normalizePersonalRecord(found) {
  return {
    status: found.status ?? "backlog",
    notes: found.notes ?? "",
    priority: found.priority ?? 0,
    hltb_override: found.hltb_override === undefined ? null : found.hltb_override,
    hidden: found.hidden === true,
    started_at: found.started_at ?? null,
    finished_at: found.finished_at ?? null,
  };
}

function hiddenTitleNorms() {
  if (!state.personal.__hidden_title_norms_v1) state.personal.__hidden_title_norms_v1 = [];
  const raw = state.personal.__hidden_title_norms_v1;
  if (!Array.isArray(raw)) return new Set();
  return new Set(raw.filter(Boolean));
}

function saveHiddenTitleNorms(norms, options) {
  const list = [...norms].sort();
  const prev = state.personal.__hidden_title_norms_v1;
  const same = Array.isArray(prev)
    && prev.length === list.length
    && prev.every((v, i) => v === list[i]);
  if (same) return false;
  state.personal.__hidden_title_norms_v1 = list;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  if (!options?.silent) scheduleDownstreamSync();
  return true;
}

export function getPersonal(g) {
  const key = gameKey(g);
  const ver = window._dataVersion || 0;
  return personalMemo.get(`${key}:${ver}`, () => {
    const found = state.personal[key] || (typeof state.personal[gameId(g)] === "object" ? state.personal[gameId(g)] : null);
    if (!found) return PERSONAL_EMPTY;
    return normalizePersonalRecord(found);
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
    const existing = state.personal[key] || { ...PERSONAL_DEFAULT };
    const { tags: _ignored, ...rest } = val;
    state.personal[key] = { ...existing, ...rest };
  }
  state.personal.__migrated_v3 = true;
  state.personal.__tags_removed_v1 = true;
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
    if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT };
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

function mirrorHiddenToKeys(keys, hidden, options) {
  const flag = !!hidden;
  let changed = false;
  for (const key of keys) {
    if (isMetaPersonalKey(key)) continue;
    if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT };
    if (state.personal[key].hidden === flag) continue;
    state.personal[key].hidden = flag;
    if (flag && options?.titleNorm) state.personal[key].hidden_title_norm = options.titleNorm;
    if (!flag && 'hidden_title_norm' in state.personal[key]) delete state.personal[key].hidden_title_norm;
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

/** One-shot: migrate key-based hidden flags into title-norm hidden set. */
export function migrateHiddenTitleNorms() {
  if (state.personal.__hidden_title_norms_migrated_v1) return false;
  const norms = hiddenTitleNorms();
  let changed = false;

  // Any catalog-backed hidden entry implies the title norm is hidden.
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (!rec || rec.hidden !== true) continue;
    const g = findGameByKey(key);
    if (!g) continue;
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    if (!norms.has(norm)) {
      norms.add(norm);
      changed = true;
    }
    if (state.personal[key] && state.personal[key].hidden_title_norm !== norm) {
      state.personal[key].hidden_title_norm = norm;
      changed = true;
    }
  }

  state.personal.__hidden_title_norms_migrated_v1 = true;
  if (changed) {
    state.personal.__hidden_title_norms_v1 = [...norms].sort();
    window._dataVersion = (window._dataVersion || 0) + 1;
    personalMemo.bump();
    savePersonal();
    scheduleDownstreamSync();
  } else {
    savePersonal();
  }
  return changed;
}

/** Apply title-level hidden norms onto whatever keys exist in the current catalog. */
export function applyHiddenTitleNorms({ silent = false } = {}) {
  migrateHiddenTitleNorms();
  const norms = hiddenTitleNorms();
  if (norms.size === 0) return false;
  const index = getTitleKeyIndex();
  let changed = false;
  for (const norm of norms) {
    const keys = index.get(norm);
    if (!keys || keys.length === 0) continue;
    if (mirrorHiddenToKeys(keys, true, { silent: true, titleNorm: norm })) changed = true;
  }
  if (changed && !silent) scheduleDownstreamSync();
  return changed;
}

/** Sync hidden flag across every store copy of the same title (fixes key churn). */
export function reconcileHiddenAcrossTitles() {
  const index = getTitleKeyIndex();
  const processed = new Set();
  let changed = false;

  const applyToGroup = (keys) => {
    const sig = keys.slice().sort().join("|");
    if (processed.has(sig)) return;
    processed.add(sig);
    const catalogKeys = keys.filter(k => findGameByKey(k));
    if (!catalogKeys.length) return;
    const anyVisible = catalogKeys.some(k => state.personal[k]?.hidden !== true);
    const target = !anyVisible;
    if (mirrorHiddenToKeys(keys, target, { silent: true })) changed = true;
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

export function canonicalizeHiddenAcrossTitles() {
  if (state.personal.__hidden_mirrored_v1) return false;
  const changed = reconcileHiddenAcrossTitles();
  state.personal.__hidden_mirrored_v1 = true;
  savePersonal();
  return changed;
}

export function setPersonalByKey(key, field, value, options) {
  if (isMetaPersonalKey(key)) return;
  if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT };
  if (field === "status") {
    const prev = state.personal[key].status || "backlog";
    const now = new Date().toISOString();
    if (value === "finished" && prev !== "finished") {
      state.personal[key].finished_at = now;
    }
    if (value === "playing" && prev !== "playing" && !state.personal[key].started_at) {
      state.personal[key].started_at = now;
    }
  }
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
  if (field === "hidden") {
    const norm = normalizeNameForDedup(g?.name);
    if (!norm) {
      mirrorHiddenToKeys(getSameTitleKeys(g), !!value, options);
      return;
    }
    const norms = hiddenTitleNorms();
    const flag = !!value;
    const didChange = flag ? !norms.has(norm) : norms.has(norm);
    if (didChange) {
      if (flag) norms.add(norm);
      else norms.delete(norm);
      saveHiddenTitleNorms(norms, options);
    }
    mirrorHiddenToKeys(getSameTitleKeys(g), flag, { ...options, titleNorm: norm });
    return;
  }
  setPersonalByKey(gameKey(g), field, value, options);
}

export function isGameHidden(g) {
  return getPersonal(g).hidden === true;
}

export function filterOutHidden(list) {
  return list.filter(g => !isGameHidden(g));
}

/** One-shot: seed pre-hidden defaults from former fetcher denylists. */
export function seedPreHiddenDefaults() {
  if (state.personal.__pre_hidden_v1_seeded) return false;
  let changed = false;
  for (const { key } of PRE_HIDDEN_KEYS) {
    if (state.personal[key]) continue;
    state.personal[key] = { ...PERSONAL_DEFAULT, hidden: true };
    changed = true;
  }
  state.personal.__pre_hidden_v1_seeded = true;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  return changed;
}

export function setGameHidden(g, hidden, options) {
  setPersonal(g, "hidden", !!hidden, options);
}

function entryDisplayName(entry) {
  if (entry.game?.name) return entry.game.name;
  if (entry.fallbackName) return entry.fallbackName;
  return entry.key;
}

/** Keys with user-hidden flag (game may still exist in catalog). */
export function listUserHiddenEntries() {
  const out = [];
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (!rec || rec.hidden !== true) continue;
    const g = findGameByKey(key);
    const fallback = g ? null : getPreHiddenFallback(key);
    out.push({
      key,
      game: g || null,
      status: rec.status || "backlog",
      notes: String(rec.notes || ""),
      fallbackName: fallback?.name || null,
      fallbackStore: fallback?.store || null,
    });
  }
  out.sort((a, b) => entryDisplayName(a).localeCompare(entryDisplayName(b)));
  return out;
}

export function countUserHiddenGames() {
  let n = 0;
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (rec?.hidden === true) n++;
  }
  return n;
}

export function countUserHiddenLibrary() {
  let n = 0;
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (rec?.hidden !== true) continue;
    if (String(key).startsWith("wishlist:")) continue;
    n++;
  }
  return n;
}

export function countUserHiddenWishlist() {
  let n = 0;
  for (const [key, rec] of Object.entries(state.personal)) {
    if (isMetaPersonalKey(key)) continue;
    if (rec?.hidden !== true) continue;
    if (!String(key).startsWith("wishlist:")) continue;
    n++;
  }
  return n;
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
    const hltbOverride = rec.hltb_override;
    const hasData = Boolean(
      rec.hidden === true ||
      (status && status !== "backlog") ||
      notes ||
      (hltbOverride != null && hltbOverride !== ""),
    );
    orphans.push({
      key,
      status: status || "backlog",
      notes,
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
