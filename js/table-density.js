/**
 * Mid-width table density: auto-hide low-priority columns so the library table
 * fits without #tableWrap overflow-x:auto (which kills sticky thead).
 */
import { state } from './state.js';

export const TABLE_DENSITY_VIEWS = ['library', 'wishlist', 'itch'];

/** Hide order: tier N includes all columns from tiers 1..N.
 *  Aggressive: free room for the Game title before other metrics. */
export const DENSITY_TIER_COLUMNS = [
  [],
  ['notes', 'genres'],
  ['notes', 'genres', 'lastplayed', 'released'],
  ['notes', 'genres', 'lastplayed', 'released', 'price', 'mc', 'score'],
  ['notes', 'genres', 'lastplayed', 'released', 'price', 'mc', 'score', 'steam'],
  ['notes', 'genres', 'lastplayed', 'released', 'price', 'mc', 'score', 'steam', 'played'],
  ['notes', 'genres', 'lastplayed', 'released', 'price', 'mc', 'score', 'steam', 'played', 'hltb'],
];

export const DENSITY_MAX_TIER = DENSITY_TIER_COLUMNS.length - 1;

/** Game title column must stay at least this wide (px) or density bumps. */
export const GAME_TITLE_MIN_PX = 168;

let _densityTier = 0;
let _densityObs = null;
let _densityRaf = 0;

function viewKey(view) {
  return TABLE_DENSITY_VIEWS.includes(view) ? view : 'library';
}

export function ensureDensityPinPrefs() {
  if (!state.prefs.columnDensityPins || typeof state.prefs.columnDensityPins !== 'object') {
    state.prefs.columnDensityPins = {};
  }
}

export function isDensityPinned(view, id) {
  ensureDensityPinPrefs();
  return !!state.prefs.columnDensityPins[viewKey(view)]?.[id];
}

export function setDensityPinned(view, id, on) {
  ensureDensityPinPrefs();
  const vk = viewKey(view);
  if (!state.prefs.columnDensityPins[vk] || typeof state.prefs.columnDensityPins[vk] !== 'object') {
    state.prefs.columnDensityPins[vk] = {};
  }
  if (on) state.prefs.columnDensityPins[vk][id] = true;
  else delete state.prefs.columnDensityPins[vk][id];
}

export function clearDensityPins(view) {
  ensureDensityPinPrefs();
  state.prefs.columnDensityPins[viewKey(view)] = {};
}

export function pinAllDensityColumns(view) {
  ensureDensityPinPrefs();
  const pins = {};
  for (const id of [
    'cover', 'score', 'played', 'hltb', 'steam', 'mc', 'price',
    'released', 'lastplayed', 'genres', 'notes',
  ]) {
    pins[id] = true;
  }
  state.prefs.columnDensityPins[viewKey(view)] = pins;
}

export function getDensityTier() {
  return _densityTier;
}

export function setDensityTier(tier) {
  _densityTier = Math.max(0, Math.min(DENSITY_MAX_TIER, Math.floor(Number(tier) || 0)));
  return _densityTier;
}

/** Columns density would hide at the given tier (ignoring pins / prefs). */
export function densityHideIdsForTier(tier) {
  const t = Math.max(0, Math.min(DENSITY_MAX_TIER, Math.floor(Number(tier) || 0)));
  return DENSITY_TIER_COLUMNS[t] || [];
}

/** True when density tier would hide this id and the user has not pinned it. */
export function densityWouldHide(view, id, tier = _densityTier) {
  if (!densityHideIdsForTier(tier).includes(id)) return false;
  return !isDensityPinned(view, id);
}

export function applyDensityTierClass(wrap, tier) {
  if (!wrap) return;
  const t = setDensityTier(tier);
  wrap.dataset.density = String(t);
  for (let i = 1; i <= DENSITY_MAX_TIER; i++) {
    wrap.classList.toggle(`table-density-${i}`, i === t);
  }
  wrap.classList.toggle('table-density', t > 0);
}

export function measureTableOverflow(wrap) {
  if (!wrap) return false;
  return wrap.scrollWidth > wrap.clientWidth + 2;
}

/** True when the Game title cell is crushed below the readable minimum. */
export function measureGameTitleTooNarrow(wrap, minPx = GAME_TITLE_MIN_PX) {
  if (!wrap) return false;
  const cell = wrap.querySelector(
    'tbody tr:not(.virtual-spacer):not(.table-empty-state-row):not(.sponsored-table-row) td.game-name-cell, '
    + 'tbody tr:not(.virtual-spacer) td.col-game',
  );
  if (!cell) return false;
  const w = cell.getBoundingClientRect().width;
  return w > 0 && w < minPx;
}

/** Need a denser tier: horizontal overflow OR crushed title. */
export function measureNeedsMoreDensity(wrap) {
  return measureTableOverflow(wrap) || measureGameTitleTooNarrow(wrap);
}

/**
 * @param {(view: string) => void} applyVisibility - applies table-hide-* for current tier
 * @param {string} view
 */
export function syncTableDensity(applyVisibility, view = state.activeView) {
  const wrap = document.getElementById('tableWrap');
  if (!wrap) return 0;
  if (wrap.classList.contains('table-phone') || !TABLE_DENSITY_VIEWS.includes(view)) {
    applyDensityTierClass(wrap, 0);
    applyVisibility?.(view);
    return 0;
  }

  let tier = 0;
  applyDensityTierClass(wrap, tier);
  applyVisibility?.(view);
  while (tier < DENSITY_MAX_TIER && measureNeedsMoreDensity(wrap)) {
    tier += 1;
    applyDensityTierClass(wrap, tier);
    applyVisibility?.(view);
  }
  while (tier > 0) {
    applyDensityTierClass(wrap, tier - 1);
    applyVisibility?.(view);
    if (measureNeedsMoreDensity(wrap)) {
      applyDensityTierClass(wrap, tier);
      applyVisibility?.(view);
      break;
    }
    tier -= 1;
  }
  return getDensityTier();
}

export function scheduleTableDensitySync(applyVisibility, view = state.activeView) {
  if (_densityRaf) cancelAnimationFrame(_densityRaf);
  _densityRaf = requestAnimationFrame(() => {
    _densityRaf = 0;
    syncTableDensity(applyVisibility, view);
  });
}

export function observeTableDensity(applyVisibility, viewGetter) {
  const wrap = document.getElementById('tableWrap');
  if (!wrap || typeof ResizeObserver !== 'function') return;
  if (_densityObs) {
    _densityObs.disconnect();
    _densityObs = null;
  }
  _densityObs = new ResizeObserver(() => {
    const view = typeof viewGetter === 'function' ? viewGetter() : state.activeView;
    scheduleTableDensitySync(applyVisibility, view);
  });
  _densityObs.observe(wrap);
  scheduleTableDensitySync(
    applyVisibility,
    typeof viewGetter === 'function' ? viewGetter() : state.activeView,
  );
}

export function isNotesColumnEffectivelyVisible(view = state.activeView) {
  const wrap = document.getElementById('tableWrap');
  if (!wrap) return true;
  if (wrap.classList.contains('table-phone')) return false;
  if (wrap.classList.contains('table-hide-notes')) return false;
  return true;
}
