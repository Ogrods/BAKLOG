/**
 * Tests for exportTopBacklogMarkdown (js/filters-ui.js) — the clipboard/markdown
 * export of the top backlog. Covers ordering, the top-20 cap, pipe escaping,
 * and the empty-backlog early return.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { state } from '../js/state.js';
import { exportTopBacklogMarkdown } from '../js/filters-ui.js';

let savedAllGames;
let savedHidden;
let savedPersonal;
let writeText;

function stubClipboard(impl) {
  writeText = vi.fn(impl);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
}

beforeEach(() => {
  savedAllGames = state.allGames;
  savedHidden = state.crossStoreHiddenKeys;
  savedPersonal = state.personal;
  state.crossStoreHiddenKeys = new Set();
  // No personal entries → every row is "backlog" and not hidden.
  state.personal = {};
  stubClipboard(() => Promise.resolve());
  vi.spyOn(window, 'alert').mockImplementation(() => {});
});

afterEach(() => {
  state.allGames = savedAllGames;
  state.crossStoreHiddenKeys = savedHidden;
  state.personal = savedPersonal;
  vi.restoreAllMocks();
});

describe('exportTopBacklogMarkdown', () => {
  it('alerts and copies nothing when there is no backlog', () => {
    state.allGames = [];
    exportTopBacklogMarkdown();
    expect(window.alert).toHaveBeenCalledWith('No backlog games to export.');
    expect(writeText).not.toHaveBeenCalled();
  });

  it('copies a markdown table ordered by priority score (desc)', () => {
    state.allGames = [
      { store: 'steam', id: 1, name: 'Low Pri', steam_review_percent: 10, hltb_main_hours: 10 },
      { store: 'steam', id: 2, name: 'High Pri', steam_review_percent: 90, hltb_main_hours: 10 },
      { store: 'gog', id: 3, name: 'Mid Pri', steam_review_percent: 50, hltb_main_hours: 10 },
    ];
    exportTopBacklogMarkdown();
    expect(writeText).toHaveBeenCalledTimes(1);
    const md = writeText.mock.calls[0][0];
    expect(md).toContain('# BAKLOG - Top 20 backlog');
    expect(md).toContain('| # | Game | Store | Score | HLTB main | Rating |');
    const rows = md.split('\n').filter(l => /^\| \d+ \|/.test(l));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toContain('High Pri');
    expect(rows[1]).toContain('Mid Pri');
    expect(rows[2]).toContain('Low Pri');
    // Store is uppercased; HLTB and rating cells are rendered.
    expect(rows[0]).toContain('| STEAM |');
    expect(rows[0]).toContain('10h');
    expect(rows[0]).toContain('90%');
    expect(rows[1]).toContain('| GOG |');
  });

  it('caps the export at the top 20 backlog games', () => {
    state.allGames = Array.from({ length: 25 }, (_, i) => ({
      store: 'steam',
      id: i + 1,
      name: `Game ${i + 1}`,
      steam_review_percent: i + 1,
      hltb_main_hours: 10,
    }));
    exportTopBacklogMarkdown();
    const md = writeText.mock.calls[0][0];
    const rows = md.split('\n').filter(l => /^\| \d+ \|/.test(l));
    expect(rows).toHaveLength(20);
  });

  it('escapes pipe characters in game names', () => {
    state.allGames = [
      { store: 'steam', id: 1, name: 'A | B', steam_review_percent: 80, hltb_main_hours: 5 },
    ];
    exportTopBacklogMarkdown();
    const md = writeText.mock.calls[0][0];
    expect(md).toContain('A \\| B');
  });

  it('falls back to download when clipboard write rejects', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')));
    const createObjectURL = vi.fn(() => 'blob:x');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    state.allGames = [
      { store: 'steam', id: 1, name: 'Solo', steam_review_percent: 80, hltb_main_hours: 5 },
    ];
    exportTopBacklogMarkdown();
    await Promise.resolve();
    await Promise.resolve();
    expect(clickSpy).toHaveBeenCalled();
    expect(createObjectURL).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
