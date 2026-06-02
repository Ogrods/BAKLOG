import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  listUserHiddenEntries,
  countUserHiddenGames,
  setGameHidden,
  setPersonalByKey,
  flushSavePersonal,
} from './personal-storage.js';
import { storeBadgeHtml, wishlistBadgeHtml, storeLetter } from './game-core.js';
import { invalidateTableCache, renderTable, pushPersonalUndo } from './table-ui.js';
import { renderSummary } from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
import { state } from './state.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

const MODAL_ID = 'hiddenPanelModal';
const LIST_ID = 'hiddenPanelList';
const SUMMARY_ID = 'hiddenPanelSummary';
const MENU_ID = 'hiddenGamesMenu';
let _hiddenPanelRelease = null;

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
  return `<span class="store-badge ${escapeAttr(store)}" title="${escapeAttr(store.toUpperCase())} (not in catalog yet)">${escapeHtml(storeLetter(store))}</span>`;
}

function rowHtml(entry) {
  const name = entryName(entry);
  return `<div class="hidden-panel-row flex items-center gap-2 p-2 rounded hover:bg-slate-700/40" data-hidden-key="${escapeAttr(entry.key)}">
    ${badgeHtml(entry)}
    <div class="flex-1 min-w-0">
      <div class="text-sm text-slate-100 truncate">${escapeHtml(name)}</div>
      <div class="text-xs text-slate-400">Last status: ${escapeHtml(entry.status)}${!entry.game ? ' · awaiting next fetch' : ''}</div>
    </div>
    <button type="button" class="hidden-restore-one text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 border border-slate-600" data-key="${escapeAttr(entry.key)}">Restore</button>
  </div>`;
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
  btn.textContent = n ? `Hidden games (${n})` : 'Hidden games';
  btn.disabled = false;
}

function render() {
  const entries = listUserHiddenEntries();
  const summary = el(SUMMARY_ID);
  if (summary) {
    summary.textContent = entries.length
      ? `${entries.length} hidden ${entries.length === 1 ? 'game' : 'games'} — restore to show in your library, wishlist, or itch tab again.`
      : 'No hidden games.';
  }
  const wrap = el(LIST_ID);
  if (!wrap) return;
  if (!entries.length) {
    wrap.innerHTML = '<div class="text-sm text-slate-400 italic p-2">Nothing is hidden. Use bulk Remove on rows in Library, Wishlist, or Itch to hide them.</div>';
    return;
  }
  wrap.innerHTML = entries.map(rowHtml).join('');
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
  const modal = el(MODAL_ID);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function unhideEntry(entry, options) {
  if (entry.game) setGameHidden(entry.game, false, options);
  else setPersonalByKey(entry.key, 'hidden', false, options);
}

function restoreKey(key) {
  const entries = listUserHiddenEntries();
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
  const entries = listUserHiddenEntries();
  if (!entries.length) return;
  if (!confirm(`Restore all ${entries.length} hidden games?`)) return;
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

export function bindHiddenPanelUI() {
  window.updateHiddenGamesMenuCount = updateHiddenGamesMenuCount;
  updateHiddenGamesMenuCount();
  el(MENU_ID)?.addEventListener('click', () => {
    document.getElementById('kebabMenu')?.classList.remove('open');
    open();
  });
  el('hiddenPanelClose')?.addEventListener('click', close);
  el('hiddenPanelCancel')?.addEventListener('click', close);
  el('hiddenPanelRestoreAll')?.addEventListener('click', restoreAll);
  el(MODAL_ID)?.addEventListener('click', e => {
    if (e.target.id === MODAL_ID) close();
  });
  el(LIST_ID)?.addEventListener('click', e => {
    const btn = e.target.closest('.hidden-restore-one');
    if (!btn?.dataset.key) return;
    restoreKey(btn.dataset.key);
  });
}
