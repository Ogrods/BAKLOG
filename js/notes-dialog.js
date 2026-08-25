/**
 * Compact notes editor when the Notes table column is density- or phone-hidden.
 */
import { findGameByKey } from './game-core.js';
import { getPersonal, setPersonal } from './personal-storage.js';
import { isNotesColumnEffectivelyVisible } from './table-density.js';
import { escapeAttr } from './dom-util.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

const MODAL_ID = 'notesDialogModal';
let _release = null;
let _activeKey = null;
/** Textarea value when the dialog was opened (for discard confirm). */
let _openedValue = '';

function el(id) {
  return document.getElementById(id);
}

export function notesAffordanceHtml(key, notesText) {
  if (isNotesColumnEffectivelyVisible()) {
    const notes = String(notesText || '').trim();
    if (!notes) return '';
    return `<span class="has-notes-dot" data-notes-key="${escapeAttr(key)}" title="${escapeAttr(notes.slice(0, 160))} - click to edit notes" aria-label="Has notes">&#9998; note</span>`;
  }
  const notes = String(notesText || '').trim();
  if (notes) {
    return `<button type="button" class="has-notes-dot notes-open-btn" data-notes-key="${escapeAttr(key)}" title="${escapeAttr(notes.slice(0, 160))} - edit notes" aria-label="Edit notes">&#9998; note</button>`;
  }
  return `<button type="button" class="notes-open-btn notes-open-btn--empty" data-notes-key="${escapeAttr(key)}" title="Add notes" aria-label="Add notes">+ note</button>`;
}

export function openNotesDialog(key) {
  const modal = el(MODAL_ID);
  const input = el('notesDialogInput');
  const title = el('notesDialogTitle');
  if (!modal || !input) return;
  const g = findGameByKey(key);
  if (!g) return;
  _activeKey = key;
  const name = g.name || 'Game';
  if (title) title.textContent = `Notes - ${name}`;
  input.value = getPersonal(g).notes || '';
  _openedValue = input.value;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  _release?.();
  const dialog = modal.querySelector('[role="dialog"]') || modal;
  const releaseTrap = trapFocus(dialog);
  const releaseEsc = bindEscapeClose(dialog, requestCloseNotesDialog);
  _release = () => {
    releaseTrap();
    releaseEsc();
    _release = null;
  };
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

/** Close without prompting (used after save or when discard is confirmed). */
export function closeNotesDialog() {
  _release?.();
  const modal = el(MODAL_ID);
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
  _activeKey = null;
  _openedValue = '';
}

/** Cancel / Escape / backdrop: confirm if the textarea differs from the opened value. */
export function requestCloseNotesDialog() {
  const input = el('notesDialogInput');
  if (input && input.value !== _openedValue) {
    if (!window.confirm('Discard unsaved notes?')) return;
  }
  closeNotesDialog();
}

function saveAndClose() {
  const key = _activeKey;
  const input = el('notesDialogInput');
  if (!key || !input) {
    closeNotesDialog();
    return;
  }
  const g = findGameByKey(key);
  if (g) setPersonal(g, 'notes', input.value);
  // Refresh affordance / notes cell without a full table rebuild when possible
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  const meta = row?.querySelector('.row-meta');
  if (meta) {
    meta.querySelectorAll('.has-notes-dot, .notes-open-btn').forEach((n) => n.remove());
    meta.insertAdjacentHTML('beforeend', notesAffordanceHtml(key, input.value));
  }
  const ta = row?.querySelector('.notes-input');
  if (ta) ta.value = input.value;
  closeNotesDialog();
}

export function bindNotesDialog() {
  el('notesDialogClose')?.addEventListener('click', requestCloseNotesDialog);
  el('notesDialogCancel')?.addEventListener('click', requestCloseNotesDialog);
  el('notesDialogSave')?.addEventListener('click', saveAndClose);
  el(MODAL_ID)?.addEventListener('click', (e) => {
    if (e.target.id === MODAL_ID) requestCloseNotesDialog();
  });
  el('notesDialogInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      saveAndClose();
    }
  });
}

/** Click handler for notes chips / + note buttons. */
export function handleNotesAffordanceClick(target) {
  const btn = target.closest('[data-notes-key], .has-notes-dot, .notes-open-btn');
  if (!btn) return false;
  const key = btn.dataset.notesKey
    || btn.closest('tr')?.dataset.rowKey;
  if (!key) return false;
  if (isNotesColumnEffectivelyVisible()) {
    const ta = btn.closest('tr')?.querySelector('.notes-input');
    if (ta) {
      ta.focus();
      return true;
    }
  }
  openNotesDialog(key);
  return true;
}
