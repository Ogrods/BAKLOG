import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  listUserHiddenEntries,
  countUserHiddenGames,
  countHiddenLibraryNoiseGames,
  setGameHidden,
  setPersonalByKey,
  flushSavePersonal,
  removeNintendoDroppedId,
} from './personal-storage.js';
import { storeBadgeHtml, wishlistBadgeHtml } from './game-core.js';
import { storeLogoHtml } from './store-logos.js';
import { invalidateTableCache, renderTable, pushPersonalUndo } from './table-ui.js';
import { renderSummary } from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
import { state } from './state.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { openBugReportDialog } from './bug-report.js';

const MODAL_ID = 'hiddenPanelModal';
const LIST_ID = 'hiddenPanelList';
const SUMMARY_ID = 'hiddenPanelSummary';
const MENU_ID = 'hiddenGamesMenu';
let _hiddenPanelRelease = null;
let _noiseOnlyFilter = false;

function el(id) { return document.getElementById(id); }

function entryName(entry) {
  return entry.game?.name || entry.fallbackName || entry.key;
}

function badgeHtml(entry) {
  const g = entry.game;
  if (g) {
    if (g.wishlist || String(g.store) === 'wishlist') return wishlistBadgeHtml(g);
    return storeBadgeHtml(g);
  }
  const store = entry.fallbackStore || 'unknown';
  return storeLogoHtml(store, { size: 'sm', title: `${store.toUpperCase()} (not in catalog yet)` });
}

function rowStatusLabel(entry) {
  if (entry.isLibraryNoise) return 'Auto-filtered (library noise)';
  return `Hidden by you · last status: ${entry.status}`;
}

function rowHtml(entry) {
  const name = entryName(entry);
  const reportBtn = entry.isLibraryNoise
    ? `<button type="button" class="hidden-noise-report text-xs px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700" data-key="${escapeAttr(entry.key)}" data-name="${escapeAttr(name)}" title="Tell us this is a real game">Not a game?</button>`
    : '';
  return `<div class="hidden-panel-row flex items-center gap-2 p-2 rounded hover:bg-slate-700/40" data-hidden-key="${escapeAttr(entry.key)}">
    ${badgeHtml(entry)}
    <div class="flex-1 min-w-0">
      <div class="text-sm text-slate-100 truncate">${escapeHtml(name)}</div>
      <div class="text-xs text-slate-400">${escapeHtml(rowStatusLabel(entry))}${!entry.game ? ' · awaiting next fetch' : ''}</div>
    </div>
    ${reportBtn}
    <button type="button" class="hidden-restore-one text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 border border-slate-600" data-key="${escapeAttr(entry.key)}">Restore</button>
  </div>`;
}

function renderSummaryText(entries) {
  if (!entries.length) {
    if (_noiseOnlyFilter) {
      return 'No auto-filtered non-games. BAKLOG hides DLC skins, soundtracks, vouchers, and similar library noise so your game count stays honest.';
    }
    return 'Nothing is hidden. Use bulk Remove on rows in Library, Wishlist, or Itch to hide them, or restore auto-filtered non-games from the library summary chip.';
  }
  const noiseCount = entries.filter(e => e.isLibraryNoise).length;
  const userCount = entries.length - noiseCount;
  if (_noiseOnlyFilter) {
    const label = entries.length === 1 ? 'non-game' : 'non-games';
    return `${entries.length} auto-filtered ${label} (library noise). Restore any row to show it in your library again.`;
  }
  const parts = [`${entries.length} hidden ${entries.length === 1 ? 'item' : 'items'}`];
  if (noiseCount) parts.push(`${noiseCount} auto-filtered non-game${noiseCount === 1 ? '' : 's'}`);
  if (userCount) parts.push(`${userCount} hidden by you`);
  return `${parts[0]}: ${parts.slice(1).join(', ')}. Restore to show in your library, wishlist, or itch tab again.`;
}

function afterHiddenChange() {
  invalidateTableCache();
  renderTable();
  renderSummary();
  renderPicks();
  if (state.activeView === 'dashboard') scheduleDashboardRender();
  updateHiddenGamesMenuCount();
}

export function updateHiddenGamesMenuCount() {
  const btn = el(MENU_ID);
  if (!btn) return;
  const n = countUserHiddenGames();
  const noise = countHiddenLibraryNoiseGames(state.allGames);
  if (!n) {
    btn.textContent = 'Hidden games';
  } else if (noise > 0 && noise < n) {
    btn.textContent = `Hidden games (${n})`;
  } else if (noise === n && noise > 0) {
    btn.textContent = `Hidden games (${n} filtered)`;
  } else {
    btn.textContent = `Hidden games (${n})`;
  }
  btn.disabled = false;
}

function render() {
  const entries = listUserHiddenEntries({ noiseOnly: _noiseOnlyFilter });
  const summary = el(SUMMARY_ID);
  if (summary) summary.textContent = renderSummaryText(entries);
  const wrap = el(LIST_ID);
  if (!wrap) return;
  if (!entries.length) {
    wrap.innerHTML = `<div class="text-sm text-slate-400 italic p-2">${escapeHtml(renderSummaryText(entries))}</div>`;
    return;
  }
  wrap.innerHTML = entries.map(rowHtml).join('');
}

export function openHiddenPanel({ noiseOnly = false } = {}) {
  _noiseOnlyFilter = !!noiseOnly;
  open();
}

function open() {
  const modal = el(MODAL_ID);
  if (!modal) return;
  const dialog = modal.querySelector('[role="dialog"]') || modal;
  render();
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  _hiddenPanelRelease?.();
  const releaseTrap = trapFocus(dialog);
  const releaseEsc = bindEscapeClose(dialog, close);
  _hiddenPanelRelease = () => {
    releaseTrap();
    releaseEsc();
    _hiddenPanelRelease = null;
  };
  el('hiddenPanelClose')?.focus();
}

function close() {
  _hiddenPanelRelease?.();
  _noiseOnlyFilter = false;
  const modal = el(MODAL_ID);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function unhideEntry(entry, options) {
  if (entry.game) {
    if (entry.game.store === 'nintendo') {
      removeNintendoDroppedId(entry.game.nintendo_id ?? entry.game.id, { silent: true });
    }
    setGameHidden(entry.game, false, options);
  } else setPersonalByKey(entry.key, 'hidden', false, options);
}

function restoreKey(key) {
  const entries = listUserHiddenEntries({ noiseOnly: _noiseOnlyFilter });
  const entry = entries.find(e => e.key === key);
  if (!entry) return;
  pushPersonalUndo({
    label: `Restored ${entryName(entry)}`,
    keys: [key],
    afterUndo: () => {
      render();
      afterHiddenChange();
    },
  });
  unhideEntry(entry, { silent: true });
  flushSavePersonal();
  render();
  afterHiddenChange();
}

function restoreAll() {
  const entries = listUserHiddenEntries({ noiseOnly: _noiseOnlyFilter });
  if (!entries.length) return;
  const scope = _noiseOnlyFilter ? 'auto-filtered non-games' : 'hidden games';
  if (!confirm(`Restore all ${entries.length} ${scope}?`)) return;
  const keys = entries.map(e => e.key);
  pushPersonalUndo({
    label: `Restored ${entries.length} hidden game${entries.length === 1 ? '' : 's'}`,
    keys,
    afterUndo: () => {
      close();
      afterHiddenChange();
    },
  });
  for (const entry of entries) unhideEntry(entry, { silent: true });
  flushSavePersonal();
  close();
  afterHiddenChange();
}

function reportFalsePositive(btn) {
  const key = btn.dataset.key || '';
  const name = btn.dataset.name || key;
  const entry = listUserHiddenEntries().find(e => e.key === key);
  const store = entry?.game?.store || entry?.fallbackStore || 'unknown';
  openBugReportDialog({
    note: `Library noise false positive: "${name}" (${store}, key: ${key}). This is a real game and should not be auto-filtered.`,
  });
}

export function bindHiddenPanelUI() {
  window.updateHiddenGamesMenuCount = updateHiddenGamesMenuCount;
  updateHiddenGamesMenuCount();
  el(MENU_ID)?.addEventListener('click', () => {
    document.getElementById('kebabMenu')?.classList.remove('open');
    openHiddenPanel();
  });
  el('hiddenPanelClose')?.addEventListener('click', close);
  el('hiddenPanelCancel')?.addEventListener('click', close);
  el('hiddenPanelRestoreAll')?.addEventListener('click', restoreAll);
  el(MODAL_ID)?.addEventListener('click', e => {
    if (e.target.id === MODAL_ID) close();
  });
  el(LIST_ID)?.addEventListener('click', e => {
    const report = e.target.closest('.hidden-noise-report');
    if (report) {
      reportFalsePositive(report);
      return;
    }
    const btn = e.target.closest('.hidden-restore-one');
    if (!btn?.dataset.key) return;
    restoreKey(btn.dataset.key);
  });
}
