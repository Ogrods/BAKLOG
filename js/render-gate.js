/**
 * Defer table/picks/summary paints when the active view cannot show them.
 */

import { state } from './state.js';
import { noteDeferredDefer } from './propagation-trace.js';

const TABLE_VIEWS = new Set(['library', 'wishlist', 'itch']);

let _deferredTable = false;
let _deferredPicks = false;
let _deferredSummary = false;

export function isTableDataView(view) {
  return TABLE_VIEWS.has(view ?? state.activeView);
}

export function deferTableRender() {
  _deferredTable = true;
  noteDeferredDefer();
}

export function deferPicksRender() {
  _deferredPicks = true;
  noteDeferredDefer();
}

export function deferSummaryRender() {
  _deferredSummary = true;
  noteDeferredDefer();
}

export function consumeDeferredRenders() {
  const flags = {
    table: _deferredTable,
    picks: _deferredPicks,
    summary: _deferredSummary,
  };
  _deferredTable = false;
  _deferredPicks = false;
  _deferredSummary = false;
  return flags;
}

/** Test helper */
export function _resetRenderGateForTests() {
  _deferredTable = false;
  _deferredPicks = false;
  _deferredSummary = false;
}
