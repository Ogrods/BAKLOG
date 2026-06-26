import { escapeHtml, escapeAttr } from './dom-util.js';
import { findGameByKey, normalizeGame } from './game-core.js';
import { storeLogoHtml } from './store-logos.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { renderPicks } from './picks-ui.js';
import { renderCustomListFilterChips } from './filters-ui.js';
import {
  CUSTOM_LIST_COUNT,
  CUSTOM_LIST_MAX_KEYS,
  getCustomLists,
  migrateCustomLists,
  renderCustomPickTabs,
} from './custom-lists.js';
import { savePrefs } from './prefs.js';
import { state } from './state.js';

const DIALOG_ID = 'customListsDialog';
const BODY_ID = 'customListsDialogBody';
let _releaseFocus = null;
let _draft = null;

function el(id) { return document.getElementById(id); }

function rowHtml(listIndex, key) {
  const g = findGameByKey(key);
  const name = g?.name || key;
  const store = g ? normalizeGame(g).store : (key.split(':')[0] || 'unknown');
  return `<div class="custom-list-row" data-list="${listIndex}" data-key="${escapeAttr(key)}">
    <span class="custom-list-row__store">${storeLogoHtml(store, { size: 'sm' })}</span>
    <span class="custom-list-row__name">${escapeHtml(name)}</span>
    <div class="custom-list-row__actions">
      <button type="button" class="custom-list-move custom-lists-dialog__btn custom-lists-dialog__btn--icon" data-delta="-1" title="Move up" aria-label="Move up">↑</button>
      <button type="button" class="custom-list-move custom-lists-dialog__btn custom-lists-dialog__btn--icon" data-delta="1" title="Move down" aria-label="Move down">↓</button>
      <button type="button" class="custom-list-remove custom-lists-dialog__btn custom-lists-dialog__btn--icon custom-lists-dialog__btn--danger" title="Remove from list" aria-label="Remove from list">✕</button>
    </div>
  </div>`;
}

function sectionHtml(listIndex, list) {
  const rows = (list.keys || []).map(k => rowHtml(listIndex, k)).join('');
  const empty = rows
    ? rows
    : '<p class="custom-list-empty">No games in this list yet.</p>';
  return `<section class="custom-list-section" data-list-section="${listIndex}">
    <div class="custom-list-section__head">
      <label class="custom-list-section__label" for="custom-list-name-${listIndex}">Name</label>
      <input type="text" id="custom-list-name-${listIndex}" class="custom-list-name" maxlength="24" data-list-name="${listIndex}" value="${escapeAttr(list.name)}" />
      <button type="button" class="custom-list-clear custom-lists-dialog__btn custom-lists-dialog__btn--secondary" data-list-clear="${listIndex}">Clear list</button>
    </div>
    <div class="custom-list-rows">${empty}</div>
    <p class="custom-list-section__meta">${(list.keys || []).length} / ${CUSTOM_LIST_MAX_KEYS} slots</p>
  </section>`;
}

function renderDialogBody() {
  const body = el(BODY_ID);
  if (!body || !_draft) return;
  body.innerHTML = _draft.map((list, i) => sectionHtml(i, list)).join('');
}

function cloneDraft() {
  _draft = migrateCustomLists({ customLists: state.prefs.customLists }).map(l => ({
    name: l.name,
    keys: [...l.keys],
  }));
}

function syncDraftToState() {
  state.prefs.customLists = _draft.map(l => ({
    name: l.name,
    keys: [...l.keys],
  }));
  savePrefs();
  renderCustomPickTabs();
  renderCustomListFilterChips();
  renderPicks();
}

export function openCustomListsDialog() {
  const dlg = el(DIALOG_ID);
  if (!dlg) return;
  cloneDraft();
  renderDialogBody();
  document.getElementById('kebabMenu')?.classList.remove('open');
  if (typeof dlg.showModal === 'function') dlg.showModal();
  else dlg.setAttribute('open', '');
  _releaseFocus = trapFocus(dlg);
  bindEscapeClose(dlg, closeCustomListsDialog);
}

export function closeCustomListsDialog() {
  const dlg = el(DIALOG_ID);
  if (!dlg) return;
  if (typeof dlg.close === 'function') dlg.close();
  else dlg.removeAttribute('open');
  _releaseFocus?.();
  _releaseFocus = null;
  _draft = null;
}

export function initCustomListsUi() {
  const dlg = el(DIALOG_ID);
  if (!dlg) return;

  document.getElementById('manageCustomListsBtn')?.addEventListener('click', () => {
    openCustomListsDialog();
  });

  dlg.addEventListener('click', e => {
    if (e.target === dlg) closeCustomListsDialog();
  });

  document.getElementById('customListsDoneBtn')?.addEventListener('click', () => {
    if (_draft) {
      for (let i = 0; i < CUSTOM_LIST_COUNT; i++) {
        const input = dlg.querySelector(`[data-list-name="${i}"]`);
        if (input) _draft[i].name = input.value.trim().slice(0, 24) || `List ${i + 1}`;
      }
      syncDraftToState();
    }
    closeCustomListsDialog();
  });

  document.getElementById('customListsPruneBtn')?.addEventListener('click', () => {
    if (!_draft) return;
    let removed = 0;
    for (let i = 0; i < CUSTOM_LIST_COUNT; i++) {
      const before = _draft[i].keys.length;
      _draft[i].keys = _draft[i].keys.filter(k => !!findGameByKey(k));
      removed += before - _draft[i].keys.length;
    }
    renderDialogBody();
    const status = el('customListsPruneStatus');
    if (status) {
      status.textContent = removed
        ? `Removed ${removed} missing ${removed === 1 ? 'game' : 'games'}.`
        : 'No missing games to prune.';
    }
  });

  dlg.addEventListener('click', e => {
    if (!_draft) return;
    const clearBtn = e.target.closest('[data-list-clear]');
    if (clearBtn) {
      const i = Number(clearBtn.dataset.listClear);
      if (Number.isFinite(i)) _draft[i].keys = [];
      renderDialogBody();
      return;
    }
    const moveBtn = e.target.closest('.custom-list-move');
    if (moveBtn) {
      const row = moveBtn.closest('.custom-list-row');
      if (!row) return;
      const li = Number(row.dataset.list);
      const key = row.dataset.key;
      const delta = Number(moveBtn.dataset.delta);
      const list = _draft[li];
      if (!list) return;
      const idx = list.keys.indexOf(key);
      if (idx < 0) return;
      const next = idx + delta;
      if (next < 0 || next >= list.keys.length) return;
      const [item] = list.keys.splice(idx, 1);
      list.keys.splice(next, 0, item);
      renderDialogBody();
      return;
    }
    const removeBtn = e.target.closest('.custom-list-remove');
    if (removeBtn) {
      const row = removeBtn.closest('.custom-list-row');
      if (!row) return;
      const li = Number(row.dataset.list);
      const key = row.dataset.key;
      _draft[li].keys = _draft[li].keys.filter(k => k !== key);
      renderDialogBody();
    }
  });
}

let _briefTimer = null;

export function showCustomListNotice(message) {
  const host = document.getElementById('migrationBanner');
  if (!host) return;
  host.textContent = message;
  host.classList.remove('hidden');
  if (_briefTimer) clearTimeout(_briefTimer);
  _briefTimer = setTimeout(() => {
    host.classList.add('hidden');
    host.textContent = '';
    _briefTimer = null;
  }, 5000);
}

export function renderBulkAddToListMenu() {
  const menu = document.getElementById('bulkAddToListMenu');
  if (!menu) return;
  const lists = getCustomLists();
  menu.innerHTML = lists.map((list, i) => {
    const n = list.keys.length;
    return `<button type="button" class="bulk-add-list" role="menuitem" data-list-index="${i}">${escapeHtml(list.name)} (${n})</button>`;
  }).join('');
}
