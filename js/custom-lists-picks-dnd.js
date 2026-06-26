/**
 * Drag-and-drop reorder for custom-list Picks tabs only (library view).
 */

import { moveCustomListKeyToIndex } from './custom-lists.js';
import { renderPicks } from './picks-ui.js';

let _dragKey = null;
let _wired = false;

function picksGrid() {
  return document.getElementById('picksGrid');
}

function listIndexFromGrid(grid) {
  const raw = grid?.dataset?.customListIndex;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 && n <= 2 ? n : -1;
}

function pickCards(grid) {
  return Array.from(grid.querySelectorAll('.pick-card:not(.sponsored-pick-card)'));
}

function clearDropTargets(grid) {
  grid?.querySelectorAll('.pick-card--drop-target').forEach(el => {
    el.classList.remove('pick-card--drop-target');
  });
}

function onDragStart(e) {
  const handle = e.target.closest('.pick-card-drag-handle');
  if (!handle) return;
  const card = handle.closest('.pick-card');
  const grid = picksGrid();
  if (!card || !grid?.classList.contains('picks-grid--custom-reorder')) return;
  _dragKey = card.dataset.gameKey || null;
  if (!_dragKey) return;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', _dragKey);
  card.classList.add('pick-card--dragging');
}

function onDragEnd() {
  _dragKey = null;
  const grid = picksGrid();
  grid?.querySelectorAll('.pick-card--dragging').forEach(el => {
    el.classList.remove('pick-card--dragging');
  });
  clearDropTargets(grid);
}

function onDragOver(e) {
  const grid = picksGrid();
  if (!grid?.classList.contains('picks-grid--custom-reorder') || !_dragKey) return;
  const card = e.target.closest('.pick-card:not(.sponsored-pick-card)');
  if (!card || card.dataset.gameKey === _dragKey) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  clearDropTargets(grid);
  card.classList.add('pick-card--drop-target');
}

function onDrop(e) {
  const grid = picksGrid();
  if (!grid?.classList.contains('picks-grid--custom-reorder')) return;
  e.preventDefault();
  const listIndex = listIndexFromGrid(grid);
  const dragKey = _dragKey || e.dataTransfer.getData('text/plain');
  const targetCard = e.target.closest('.pick-card:not(.sponsored-pick-card)');
  clearDropTargets(grid);
  onDragEnd();
  if (!dragKey || !targetCard || listIndex < 0) return;
  const targetKey = targetCard.dataset.gameKey;
  if (!targetKey || targetKey === dragKey) return;
  const cards = pickCards(grid);
  const toIndex = cards.findIndex(c => c.dataset.gameKey === targetKey);
  if (toIndex < 0) return;
  if (!moveCustomListKeyToIndex(listIndex, dragKey, toIndex)) return;
  renderPicks();
}

export function initCustomListPicksDnd() {
  if (_wired) return;
  _wired = true;
  const grid = picksGrid();
  if (!grid) return;
  grid.addEventListener('dragstart', onDragStart);
  grid.addEventListener('dragend', onDragEnd);
  grid.addEventListener('dragover', onDragOver);
  grid.addEventListener('dragleave', e => {
    if (!e.target.closest?.('.pick-card')) clearDropTargets(picksGrid());
  });
  grid.addEventListener('drop', onDrop);
}
