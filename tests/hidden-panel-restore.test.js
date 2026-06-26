/**
 * Hidden-games panel restore surface (re-audit bucket 2).
 *
 * Exercises the real hidden-panel UI (open via kebab, per-row Restore, Restore
 * all) plus the orphan-key fallback path where a hidden key has no catalog game.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';

let state;
let bindHiddenPanelUI;
let openHiddenPanel;
let updateHiddenGamesMenuCount;
let setGameHidden;
let setPersonalByKey;
let getPersonal;
let gameKey;
let PRE_HIDDEN_KEYS;

const a = { store: 'steam', id: 1, name: 'Alpha', playtime_minutes: 0 };
const b = { store: 'steam', id: 2, name: 'Bravo', playtime_minutes: 0 };
const noise = { store: 'epic', id: 3, name: 'YouTube', tags: ['noise'], playtime_minutes: 0 };

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  vi.useFakeTimers();
  vi.stubGlobal('confirm', vi.fn(() => true));
  hydrateIndexDocument();

  ({ state } = await import('../js/state.js'));
  ({ bindHiddenPanelUI, openHiddenPanel, updateHiddenGamesMenuCount } = await import('../js/hidden-panel.js'));
  ({ setGameHidden, setPersonalByKey, getPersonal } = await import('../js/personal-storage.js'));
  ({ gameKey } = await import('../js/game-core.js'));
  ({ PRE_HIDDEN_KEYS } = await import('../js/hidden-defaults.js'));

  state.personal = {};
  state.allGames = [a, b];
  state.wishlistGames = [];
  state.itchGames = [];
  state.activeView = 'library';
  window._dataVersion = 0;

  bindHiddenPanelUI();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function openPanel() {
  document.getElementById('hiddenGamesMenu').click();
}

describe('hidden panel count badge', () => {
  it('reflects the number of user-hidden games', () => {
    expect(document.getElementById('hiddenGamesMenu').textContent).toBe('Hidden games');
    setGameHidden(a, true, { silent: true });
    updateHiddenGamesMenuCount();
    expect(document.getElementById('hiddenGamesMenu').textContent).toBe('Hidden games (1)');
  });
});

describe('per-row Restore', () => {
  it('restores a single hidden game and updates the count', () => {
    setGameHidden(a, true, { silent: true });
    setGameHidden(b, true, { silent: true });
    openPanel();

    const rows = document.querySelectorAll('#hiddenPanelList .hidden-restore-one');
    expect(rows.length).toBe(2);

    const aBtn = document.querySelector(`#hiddenPanelList .hidden-restore-one[data-key="${gameKey(a)}"]`);
    aBtn.click();

    expect(getPersonal(a).hidden).toBe(false);
    expect(getPersonal(b).hidden).toBe(true);
    expect(document.getElementById('hiddenGamesMenu').textContent).toBe('Hidden games (1)');
  });
});

describe('Restore all', () => {
  it('clears every hidden flag after confirmation', () => {
    setGameHidden(a, true, { silent: true });
    setGameHidden(b, true, { silent: true });
    openPanel();

    document.getElementById('hiddenPanelRestoreAll').click();

    expect(getPersonal(a).hidden).toBe(false);
    expect(getPersonal(b).hidden).toBe(false);
    expect(document.getElementById('hiddenGamesMenu').textContent).toBe('Hidden games');
  });
});

describe('library noise copy', () => {
  it('labels auto-filtered rows and offers false-positive report', () => {
    state.allGames = [a, noise];
    setGameHidden(noise, true, { silent: true });
    openHiddenPanel({ noiseOnly: true });

    const summary = document.getElementById('hiddenPanelSummary').textContent;
    expect(summary).toMatch(/auto-filtered/i);
    const row = document.querySelector(`#hiddenPanelList [data-hidden-key="${gameKey(noise)}"]`);
    expect(row.textContent).toMatch(/library noise/i);
    expect(document.querySelector('.hidden-noise-report')).toBeTruthy();
  });
});

describe('orphan-key fallback', () => {
  it('lists a hidden key with no catalog game and restores it via setPersonalByKey', () => {
    const orphanKey = PRE_HIDDEN_KEYS[0].key;
    setPersonalByKey(orphanKey, 'hidden', true, { silent: true });
    openPanel();

    const row = document.querySelector(`#hiddenPanelList .hidden-restore-one[data-key="${orphanKey}"]`);
    expect(row).toBeTruthy();
    // The row label falls back to the pre-hidden name, not the raw key.
    const labelText = document.querySelector(`#hiddenPanelList [data-hidden-key="${orphanKey}"]`).textContent;
    expect(labelText).toContain('awaiting next fetch');

    row.click();
    expect(state.personal[orphanKey].hidden).toBe(false);
  });
});
