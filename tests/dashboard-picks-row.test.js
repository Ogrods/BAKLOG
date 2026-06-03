/** Dashboard picks row layout — itch visibility and recents card. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('dashboard picks row', () => {
  let applyItchVisibility;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    win.document.body.innerHTML = `
      <div id="dashboardPicksRow" class="dash-picks-row">
        <div id="dashPicksVersusCard" class="dash-picks-versus"></div>
        <div id="dashItchCard" class="dash-card-itch"></div>
        <div id="dashRecentCard" class="dash-recent-card">
          <div id="dashRecentAdditions" class="dash-recent-list"></div>
        </div>
      </div>`;

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ applyItchVisibility } = await import('../js/dashboard-cards.js'));
    state.itchGames = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows recents card and no-itch when itch library is empty', () => {
    applyItchVisibility();
    const row = document.getElementById('dashboardPicksRow');
    const itch = document.getElementById('dashItchCard');
    const recent = document.getElementById('dashRecentCard');
    expect(row.classList.contains('no-itch')).toBe(true);
    expect(itch.classList.contains('hidden')).toBe(true);
    expect(recent.classList.contains('hidden')).toBe(false);
  });

  it('removes no-itch and shows itch card when itch data exists', () => {
    state.itchGames = [{ store: 'itch', id: 'a', name: 'Demo' }];
    applyItchVisibility();
    const row = document.getElementById('dashboardPicksRow');
    const itch = document.getElementById('dashItchCard');
    expect(row.classList.contains('no-itch')).toBe(false);
    expect(itch.classList.contains('hidden')).toBe(false);
  });
});
