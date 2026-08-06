import { state } from './state.js';
import { savePrefs } from './prefs.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { escapeHtml } from './dom-util.js';
import {
  toggleableColumns,
  columnsForPicker,
  isColumnVisible,
  setColumnVisible,
  resetColumns,
  showAllColumns,
  applyColumnVisibility,
} from './table-columns.js';
import { scheduleTableDensitySync } from './table-density.js';

const MODAL_ID = 'columnsModal';
const LIST_ID = 'columnsList';
let _release = null;

function el(id) { return document.getElementById(id); }

function currentView() {
  const view = state.activeView;
  return view === 'library' || view === 'wishlist' || view === 'itch' ? view : 'library';
}

function rowHtml(col, view) {
  const checked = isColumnVisible(view, col.id);
  const title = col.label;
  return `<label class="columns-picker-row flex items-center gap-2 text-sm text-slate-200 py-1 px-1.5 rounded cursor-pointer">
    <input type="checkbox" class="rounded columns-picker-check" data-column-id="${escapeHtml(col.id)}" ${checked ? 'checked' : ''} />
    <span>${escapeHtml(title)}</span>
  </label>`;
}

function render() {
  const list = el(LIST_ID);
  if (!list) return;
  const view = currentView();
  const cols = columnsForPicker(view);
  list.innerHTML = cols.map(c => rowHtml(c, view)).join('');
}

function persistAndApply(view) {
  savePrefs();
  applyColumnVisibility(view);
  scheduleTableDensitySync((v) => applyColumnVisibility(v), view);
}

function open() {
  const modal = el(MODAL_ID);
  if (!modal) return;
  const dialog = modal.querySelector('[role="dialog"]') || modal;
  render();
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  _release?.();
  const releaseTrap = trapFocus(dialog);
  const releaseEsc = bindEscapeClose(dialog, close);
  _release = () => {
    releaseTrap();
    releaseEsc();
    _release = null;
  };
  el('columnsModalClose')?.focus();
}

function close() {
  _release?.();
  const modal = el(MODAL_ID);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

export function bindColumnPicker() {
  el('openColumnsBtn')?.addEventListener('click', open);
  el('columnsModalClose')?.addEventListener('click', close);
  el('columnsModalCancel')?.addEventListener('click', close);
  el('columnsShowAllBtn')?.addEventListener('click', () => {
    const view = currentView();
    showAllColumns(view);
    persistAndApply(view);
    render();
  });
  el('columnsResetBtn')?.addEventListener('click', () => {
    const view = currentView();
    resetColumns(view);
    persistAndApply(view);
    render();
  });
  el(MODAL_ID)?.addEventListener('click', e => {
    if (e.target.id === MODAL_ID) close();
  });
  el(LIST_ID)?.addEventListener('change', e => {
    const input = e.target.closest('.columns-picker-check');
    if (!input?.dataset.columnId) return;
    const view = currentView();
    setColumnVisible(view, input.dataset.columnId, input.checked);
    persistAndApply(view);
  });
}
