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
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="row-ctl rounded text-xs" title="Set your backlog status — saves immediately">${inner}</select>`;
}
