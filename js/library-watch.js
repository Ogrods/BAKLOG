/**
 * Watch for specific games to appear in a store catalog (e.g. Steam API lag
 * after a new purchase). Persists per profile; checks after Steam sync and
 * on a light poll while the tab is open.
 */

import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import { profileScopedStorageKey } from './profiles.js';
import { fetchLibraryJson } from './library-load.js';
import { applyPrefsChange, switchView } from './filters-ui.js';
import { syncFilterDomFromState } from './prefs.js';
import { invalidateTableCache, renderTable } from './table-ui.js';

const WATCH_LS_KEY = profileScopedStorageKey('baklog-library-watch');
const POLL_MS = 5 * 60 * 1000;

/** PICO PARK (2021) and Pico Park Classic — either counts. */
export const PICO_PARK_WATCH = {
  id: 'pico-park',
  name: 'PICO PARK',
  store: 'steam',
  appids: [1509960, 453090],
};

let _pollTimer = null;

function loadDoc() {
  try {
    const raw = JSON.parse(localStorage.getItem(WATCH_LS_KEY) || '{}');
    const watches = raw?.watches;
    return Array.isArray(watches) ? watches : [];
  } catch {
    return [];
  }
}

function saveDoc(watches) {
  try {
    localStorage.setItem(WATCH_LS_KEY, JSON.stringify({ watches }));
  } catch {
    /* storage full / private mode */
  }
}

export function listArmedWatches() {
  return loadDoc();
}

export function hasArmedWatches() {
  return loadDoc().length > 0;
}

/** Arm a watch (deduped by id). Requests desktop notification permission once. */
export function armLibraryWatch(watch) {
  const watches = loadDoc();
  if (!watches.some(w => w.id === watch.id)) {
    watches.push({
      ...watch,
      armedAt: new Date().toISOString(),
    });
    saveDoc(watches);
  }
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
  renderWaitingBanner();
  scheduleWatchPoll();
}

export function dismissLibraryWatch(watchId) {
  saveDoc(loadDoc().filter(w => w.id !== watchId));
  renderWaitingBanner();
  if (!hasArmedWatches()) stopWatchPoll();
}

function findInSteamCatalog(games, watch) {
  if (!Array.isArray(games)) return null;
  const ids = new Set(watch.appids || []);
  return games.find(g => ids.has(g.appid)) || null;
}

function postDesktopNotification(title, body) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    new Notification(title, { body, tag: 'baklog-library-watch' });
  } catch {
    /* unsupported */
  }
}

function showFoundBanner(watch, game) {
  const el = document.getElementById('libraryWatchBanner');
  if (!el) return;
  const displayName = game?.name || watch.name;
  el.innerHTML = `
    <div class="migration-banner-body library-watch-found">
      <span><strong>${escapeHtml(displayName)}</strong> is now in your Steam library.</span>
      <span class="migration-banner-actions">
        <button type="button" class="fh-log-btn" data-lw-view>View in library</button>
        <button type="button" class="fh-log-btn" data-lw-dismiss>Dismiss</button>
      </span>
    </div>`;
  el.classList.remove('hidden');
  el.querySelector('[data-lw-view]')?.addEventListener('click', () => {
    el.classList.add('hidden');
    applyPrefsChange({ sessionPrefs: { search: displayName } });
    syncFilterDomFromState();
    if (state.activeView !== 'library') switchView('library');
    else {
      invalidateTableCache();
      renderTable();
    }
  }, { once: true });
  el.querySelector('[data-lw-dismiss]')?.addEventListener('click', () => {
    el.classList.add('hidden');
  }, { once: true });
}

export function renderWaitingBanner() {
  const el = document.getElementById('libraryWatchBanner');
  if (!el) return;
  const watches = loadDoc();
  if (!watches.length) {
    el.classList.add('hidden');
    el.innerHTML = '';
    return;
  }
  const labels = watches.map(w => escapeHtml(w.name)).join(', ');
  el.innerHTML = `
    <div class="migration-banner-body library-watch-waiting">
      <span>Waiting for <strong>${labels}</strong> in your Steam library.
        Steam's API can lag behind the client - we'll alert you when the next sync includes it.</span>
      <span class="migration-banner-actions">
        <button type="button" class="fh-log-btn" data-lw-run-steam>Run Steam fetch</button>
        <button type="button" class="fh-log-btn" data-lw-cancel-watch>Stop watching</button>
      </span>
    </div>`;
  el.classList.remove('hidden');
  el.querySelector('[data-lw-run-steam]')?.addEventListener('click', () => {
    import('./fetcher-health.js').then(({ fetcherRunner }) => {
      fetcherRunner.run('steam', { auto: false }).catch(() => {});
    });
  });
  el.querySelector('[data-lw-cancel-watch]')?.addEventListener('click', () => {
    saveDoc([]);
    el.classList.add('hidden');
    stopWatchPoll();
  });
}

function fireWatchAlert(watch, game) {
  const name = game?.name || watch.name;
  postDesktopNotification('BAKLOG - game added', `${name} is now in your Steam library.`);
  showFoundBanner(watch, game);
  console.info(`[library-watch] ${name} detected in Steam catalog`);
}

/**
 * Check armed watches against the current in-memory Steam catalog.
 * Returns true if any watch fired.
 */
export function checkLibraryWatches() {
  const watches = loadDoc();
  if (!watches.length) return false;
  const games = state.libraryMeta?.steam?.games;
  let fired = false;
  const remaining = [];
  for (const watch of watches) {
    const hit = findInSteamCatalog(games, watch);
    if (hit) {
      fireWatchAlert(watch, hit);
      fired = true;
    } else {
      remaining.push(watch);
    }
  }
  if (fired) {
    saveDoc(remaining);
    if (remaining.length) {
      renderWaitingBanner();
    }
    if (!remaining.length) stopWatchPoll();
  }
  return fired;
}

async function pollSteamCatalog() {
  if (document.hidden || !hasArmedWatches()) return;
  try {
    const steam = await fetchLibraryJson('games_steam.json');
    if (steam?.games) {
      state.libraryMeta.steam = steam;
      checkLibraryWatches();
    }
  } catch {
    /* offline / no file yet */
  }
}

function scheduleWatchPoll() {
  stopWatchPoll();
  if (!hasArmedWatches()) return;
  _pollTimer = setInterval(() => {
    void pollSteamCatalog();
  }, POLL_MS);
}

function stopWatchPoll() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

/** Boot: drop the legacy auto-armed Pico Park watch, then resume any user watches. */
export function initLibraryWatches() {
  // Pico Park was auto-armed for a one-off request; clear it so the waiting
  // banner no longer reappears on every boot.
  dismissLibraryWatch(PICO_PARK_WATCH.id);
  renderWaitingBanner();
  checkLibraryWatches();
  scheduleWatchPoll();
}

export function onSteamCatalogReloaded() {
  checkLibraryWatches();
  if (hasArmedWatches()) scheduleWatchPoll();
}
