import { describe, it, expect, beforeEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';

let state;
let renderSummary;
let setGameHidden;
let tagNoiseRow;
let openHiddenPanel;

const real = { store: 'steam', id: 1, name: 'Hades', tags: [] };
const noise = { store: 'epic', id: 2, name: 'YouTube', tags: [] };

beforeEach(async () => {
  vi.resetModules();
  hydrateIndexDocument();
  ({ state } = await import('../js/state.js'));
  ({ renderSummary } = await import('../js/filters-ui.js'));
  ({ setGameHidden } = await import('../js/personal-storage.js'));
  ({ tagNoiseRow } = await import('../js/library-noise.js'));
  ({ openHiddenPanel } = await import('../js/hidden-panel.js'));

  state.personal = {};
  state.allGames = [real, noise];
  state.wishlistGames = [];
  state.itchGames = [];
  state.activeView = 'library';
  state.sessionPrefs = { staleOnly: false };
  state.prefs = { storeFilter: '', genreFilters: [] };
  state.crossStoreHiddenKeys = new Set();
});

describe('renderSummary noise chip', () => {
  it('omits chip when no hidden library noise rows', () => {
    renderSummary();
    const html = document.getElementById('summary').innerHTML;
    expect(html).not.toContain('summary-noise-chip');
    expect(html).not.toContain('data-open-noise-hidden');
  });

  it('shows chip with count when library noise is auto-hidden', () => {
    tagNoiseRow(noise);
    setGameHidden(noise, true, { silent: true });
    renderSummary();
    const chip = document.querySelector('.summary-noise-chip[data-open-noise-hidden="1"]');
    expect(chip).toBeTruthy();
    expect(chip.textContent).toMatch(/Filtered/);
    expect(chip.textContent).toMatch(/1/);
    expect(chip.textContent).toMatch(/non-games/);
  });
});

describe('summary noise chip opens hidden panel', () => {
  it('opens noise-only hidden panel on chip click', async () => {
    const { bindHiddenPanelUI } = await import('../js/hidden-panel.js');
    bindHiddenPanelUI();
    tagNoiseRow(noise);
    setGameHidden(noise, true, { silent: true });
    renderSummary();
    document.getElementById('summary').addEventListener('click', (e) => {
      const chip = e.target.closest('.summary-noise-chip[data-open-noise-hidden]');
      if (chip) openHiddenPanel({ noiseOnly: true });
    });
    document.querySelector('.summary-noise-chip').click();
    expect(document.getElementById('hiddenPanelModal').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('hiddenPanelSummary').textContent).toMatch(/auto-filtered/i);
  });
});
