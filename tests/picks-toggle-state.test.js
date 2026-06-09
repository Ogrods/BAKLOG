/** Picks panel collapsed state — container + button stay in sync. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('applyPicksCollapsedState', () => {
  let applyPicksCollapsedState;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    win.document.body.innerHTML = `
      <section id="picksSection">
        <button id="togglePicks" title="Hide or show the Picks panel">Hide</button>
        <div id="picksContainer" class="p-3"></div>
      </section>`;

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ applyPicksCollapsedState } = await import('../js/picks-ui.js'));
    state.prefs = {};
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function containerHidden() {
    return document.getElementById('picksContainer').classList.contains('hidden');
  }

  function buttonText() {
    return document.getElementById('togglePicks').textContent;
  }

  it('undefined picksCollapsed opens panel and shows Hide', () => {
    state.prefs.picksCollapsed = undefined;
    applyPicksCollapsedState();
    expect(state.prefs.picksCollapsed).toBe(false);
    expect(containerHidden()).toBe(false);
    expect(buttonText()).toBe('Hide');
  });

  it('true picksCollapsed hides panel and shows Show', () => {
    state.prefs.picksCollapsed = true;
    applyPicksCollapsedState();
    expect(state.prefs.picksCollapsed).toBe(true);
    expect(containerHidden()).toBe(true);
    expect(buttonText()).toBe('Show');
  });

  it('false picksCollapsed shows panel and shows Hide', () => {
    state.prefs.picksCollapsed = false;
    applyPicksCollapsedState();
    expect(state.prefs.picksCollapsed).toBe(false);
    expect(containerHidden()).toBe(false);
    expect(buttonText()).toBe('Hide');
  });
});
