/**
 * Tests for js/table-columns.js — per-view column visibility prefs.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  isColumnVisible,
  setColumnVisible,
  resetColumns,
  migrateColumnPrefs,
  toggleableColumns,
} from '../js/table-columns.js';

beforeEach(() => {
  state.prefs = { columns: {} };
});

describe('table-columns', () => {
  it('uses per-view defaults when no override is stored', () => {
    expect(isColumnVisible('library', 'score')).toBe(false);
    expect(isColumnVisible('library', 'played')).toBe(true);
    expect(isColumnVisible('wishlist', 'played')).toBe(false);
    expect(isColumnVisible('wishlist', 'lastplayed')).toBe(false);
  });

  it('locked columns are always visible', () => {
    setColumnVisible('library', 'game', false);
    expect(isColumnVisible('library', 'game')).toBe(true);
    expect(isColumnVisible('library', 'status')).toBe(true);
  });

  it('persists overrides per view', () => {
    setColumnVisible('library', 'score', true);
    setColumnVisible('wishlist', 'score', false);
    expect(isColumnVisible('library', 'score')).toBe(true);
    expect(isColumnVisible('wishlist', 'score')).toBe(false);
  });

  it('resetColumns restores defaults for one view', () => {
    setColumnVisible('library', 'score', true);
    setColumnVisible('library', 'notes', false);
    resetColumns('library');
    expect(isColumnVisible('library', 'score')).toBe(false);
    expect(isColumnVisible('library', 'notes')).toBe(true);
  });

  it('migrateColumnPrefs maps legacy score/mc flags into all views', () => {
    const merged = { showScoreColumn: true, showMetacriticColumn: false, columns: {} };
    migrateColumnPrefs(merged);
    expect(merged.showScoreColumn).toBeUndefined();
    expect(merged.showMetacriticColumn).toBeUndefined();
    expect(merged.columns.library.score).toBe(true);
    expect(merged.columns.wishlist.mc).toBe(false);
  });

  it('lists every data column except locked ones as toggleable', () => {
    const ids = toggleableColumns().map(c => c.id);
    expect(ids).toContain('cover');
    expect(ids).toContain('notes');
    expect(ids).not.toContain('game');
    expect(ids).not.toContain('select');
    expect(ids).not.toContain('status');
  });
});
