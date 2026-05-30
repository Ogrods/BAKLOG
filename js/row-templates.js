import { escapeAttr } from './table-query.js';

export const STATUS_LABELS = {
  backlog: 'Backlog',
  next: 'Next up',
  playing: 'Playing',
  unfinished: 'Unfinished',
  live: 'Live service',
  finished: 'Finished',
  skip: 'Skip',
};

export const WISHLIST_STATUS_LABELS = {
  backlog: 'Watching',
  next: 'Want it',
  skip: 'Pass',
  finished: 'Bought',
};

const STATUS_VALUES = Object.keys(STATUS_LABELS);

export function buildStatusSelect(key, current) {
  const inner = STATUS_VALUES.map(
    v => `<option value="${v}"${v === current ? ' selected' : ''}>${STATUS_LABELS[v]}</option>`,
  ).join('');
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="row-ctl bg-slate-700 border border-slate-600 rounded text-xs">${inner}</select>`;
}

export function buildPrioritySelect(key, current) {
  const inner = [0, 1, 2, 3, 4, 5].map(
    n => `<option value="${n}"${n === current ? ' selected' : ''}>${n || '—'}</option>`,
  ).join('');
  return `<select data-game-key="${escapeAttr(key)}" data-field="priority" class="row-ctl bg-slate-700 border border-slate-600 rounded text-xs">${inner}</select>`;
}
