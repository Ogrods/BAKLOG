/**
 * Manual orphan-personal-data cleanup modal.
 *
 * Surface (A): debug overlay shows an `orphans` count.
 * Manual prune (B): kebab → "Clean up unknown games…" opens this modal.
 *
 * Why manual-only: an auto-prune that runs before every catalog has finished
 * loading would silently nuke valid data (e.g. fetch_steam.py failed today
 * → every Steam key would orphan). The server's rotating backup in
 * data/personal_backups/ is the recoverability story for accidental clicks.
 */

import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  findOrphanPersonalKeys,
  prunePersonalKeys,
  flushSavePersonal,
} from './personal-storage.js';

const MODAL_ID = 'orphanPruneModal';
const LIST_ID = 'orphanPruneList';
const SUMMARY_ID = 'orphanPruneSummary';
const EMPTY_FILTER_ID = 'orphanPruneEmptyOnly';

function el(id) { return document.getElementById(id); }

function statusLabel(rec) {
  return rec.status || 'backlog';
}

function notesPreview(rec) {
  if (!rec.notes) return '';
  return rec.notes.length > 80 ? `${rec.notes.slice(0, 80)}…` : rec.notes;
}

function rowHtml(rec) {
  const tagPart = rec.tags.length ? `${rec.tags.length} tag${rec.tags.length === 1 ? '' : 's'}` : '';
  const notePart = rec.notes ? `note: ${escapeHtml(notesPreview(rec))}` : '';
  const hltbPart = rec.hltbOverride != null && rec.hltbOverride !== '' ? `hltb ${rec.hltbOverride}h` : '';
  const dataBits = [tagPart, notePart, hltbPart].filter(Boolean).join(' · ');
  const dataHtml = dataBits ? `<div class="text-xs text-slate-400 truncate">${dataBits}</div>` : '';
  const meta = rec.hasData
    ? `<span class="text-amber-400" title="Has saved data (status / notes / tags / HLTB)">●</span>`
    : `<span class="text-slate-500" title="Default record (no edits)">○</span>`;
  return `<label class="flex items-start gap-2 p-2 rounded hover:bg-slate-700/40 cursor-pointer" data-orphan-row="${escapeAttr(rec.key)}">
    <input type="checkbox" class="orphan-row-checkbox mt-0.5" data-key="${escapeAttr(rec.key)}" ${rec.hasData ? '' : 'checked'} />
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 text-sm">
        ${meta}
        <code class="text-slate-200">${escapeHtml(rec.key)}</code>
        <span class="text-xs text-slate-400">${escapeHtml(statusLabel(rec))}</span>
      </div>
      ${dataHtml}
    </div>
  </label>`;
}

let _cachedOrphans = [];

function render() {
  const all = findOrphanPersonalKeys();
  _cachedOrphans = all;
  const emptyOnly = !!el(EMPTY_FILTER_ID)?.checked;
  const list = emptyOnly ? all.filter(o => !o.hasData) : all;
  const summary = el(SUMMARY_ID);
  if (summary) {
    const totals = `${all.length} orphan${all.length === 1 ? '' : 's'} · ${all.filter(o => o.hasData).length} with data · ${all.filter(o => !o.hasData).length} empty`;
    summary.textContent = totals + (emptyOnly && all.length !== list.length ? ` · showing ${list.length}` : '');
  }
  const wrap = el(LIST_ID);
  if (!wrap) return;
  if (!list.length) {
    wrap.innerHTML = '<div class="text-sm text-slate-400 italic p-2">No orphan personal records. Every stored entry has a matching game.</div>';
    return;
  }
  wrap.innerHTML = list.map(rowHtml).join('');
}

function open() {
  const modal = el(MODAL_ID);
  if (!modal) return;
  if (!state.dashboardDataReady) {
    alert("Library is still loading. Wait until the boot curtain lifts before pruning so we don't flag valid games as orphan.");
    return;
  }
  render();
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function close() {
  const modal = el(MODAL_ID);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function selectedKeys() {
  return Array.from(document.querySelectorAll('.orphan-row-checkbox:checked')).map(cb => cb.dataset.key);
}

function confirmPrune() {
  const keys = selectedKeys();
  if (!keys.length) {
    alert('Nothing selected.');
    return;
  }
  const ok = confirm(`Remove personal data for ${keys.length} unknown ${keys.length === 1 ? 'entry' : 'entries'}?\n\nThe server keeps a rotating backup in data/personal_backups/ — you can restore from there if needed.`);
  if (!ok) return;
  const removed = prunePersonalKeys(keys);
  flushSavePersonal();
  close();
  console.log(`[orphan-prune] removed ${removed} orphan personal record${removed === 1 ? '' : 's'}`);
}

export function bindOrphanPruneUI() {
  el('cleanupOrphanPersonal')?.addEventListener('click', () => {
    document.getElementById('kebabMenu')?.classList.remove('open');
    open();
  });
  el('orphanPruneClose')?.addEventListener('click', close);
  el('orphanPruneCancel')?.addEventListener('click', close);
  el('orphanPruneConfirm')?.addEventListener('click', confirmPrune);
  el('orphanPruneSelectAll')?.addEventListener('click', () => {
    document.querySelectorAll('.orphan-row-checkbox').forEach(cb => { cb.checked = true; });
  });
  el('orphanPruneSelectNone')?.addEventListener('click', () => {
    document.querySelectorAll('.orphan-row-checkbox').forEach(cb => { cb.checked = false; });
  });
  el(EMPTY_FILTER_ID)?.addEventListener('change', render);
  el(MODAL_ID)?.addEventListener('click', (ev) => {
    if (ev.target?.id === MODAL_ID) close();
  });
}

export { open as openOrphanPruneModal };
