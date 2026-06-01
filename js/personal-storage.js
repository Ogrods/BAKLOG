import { state, STORAGE_KEY, MANUAL_KEY } from './state.js';
import { personalStore, configurePersonalStore } from './personal-store.js';
import { createMemo } from './memo.js';
import { gameKey, gameId } from './game-core.js';

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

export function setPersonal(g, field, value, options) {
  const key = gameKey(g);
  if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT, tags: [] };
  if (!Array.isArray(state.personal[key].tags)) state.personal[key].tags = [];
  state.personal[key][field] = value;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  if (options?.silent) return;
  scheduleDownstreamSync();
}

export function normalizeTag(t) {
  return String(t || "").trim().toLowerCase().replace(/\s+/g, " ").slice(0, 32);
}

export function addTagToGame(g, raw) {
  const tag = normalizeTag(raw);
  if (!tag) return false;
  const cur = getPersonal(g).tags;
  if (cur.includes(tag)) return false;
  setPersonal(g, "tags", [...cur, tag].sort());
  return true;
}

export function removeTagFromGame(g, tag) {
  const cur = getPersonal(g).tags;
  if (!cur.includes(tag)) return false;
  setPersonal(g, "tags", cur.filter(x => x !== tag));
  return true;
}

export function allPersonalTags() {
  const counts = new Map();
  for (const v of Object.values(state.personal)) {
    if (!v || typeof v !== "object" || !Array.isArray(v.tags)) continue;
    for (const t of v.tags) counts.set(t, (counts.get(t) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
