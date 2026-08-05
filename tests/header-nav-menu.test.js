import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  closeHeaderNavMenu,
  headerNavSheetClassForTest,
  initHeaderNavMenu,
  isHeaderNavMenuOpen,
  openHeaderNavMenu,
} from '../js/header-nav-menu.js';

function mount() {
  document.documentElement.classList.remove(headerNavSheetClassForTest());
  document.body.innerHTML = `
    <div class="app-header-row" style="width:400px">
      <div class="app-header-brand" style="width:80px">BAKLOG</div>
      <div id="appHeaderNavWrap">
        <div id="headerNavBackdrop" hidden></div>
        <div id="headerNavPanel">
          <nav id="appHeaderNav" class="app-header-nav" style="width:600px">
            <button type="button" class="view-tab" data-view="dashboard">Dashboard</button>
            <button type="button" class="view-tab active" data-view="library">Library</button>
          </nav>
          <div id="headerNavSheetExtras" class="header-nav-sheet-extras" hidden></div>
        </div>
      </div>
      <div class="app-header-actions" style="width:120px">
        <button type="button" id="headerNavToggle" aria-expanded="false">Menu</button>
        <button type="button" id="headerFullscreenBtn">FS</button>
        <button type="button" id="reportBugHeader">Bug<span class="header-nav-sheet-action-label">Report bug</span></button>
        <div id="profileMenuWrap"><button type="button" id="profileMenuTrigger">Default</button></div>
      </div>
    </div>`;
}

describe('header nav hamburger menu', () => {
  beforeEach(() => {
    mount();
  });

  afterEach(() => {
    closeHeaderNavMenu();
    document.documentElement.classList.remove(headerNavSheetClassForTest());
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('opens as dialog sheet when tablet mq / sheet class is active', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: String(query).includes('1023.98'),
      media: String(query),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }));
    initHeaderNavMenu();

    expect(document.documentElement.classList.contains(headerNavSheetClassForTest())).toBe(true);
    expect(openHeaderNavMenu()).toBe(true);
    const panel = document.getElementById('headerNavPanel');
    expect(panel.hidden).toBe(false);
    expect(panel.getAttribute('aria-modal')).toBe('true');
    expect(document.getElementById('appHeaderNavWrap').classList.contains('is-open')).toBe(true);
    expect(document.getElementById('headerNavToggle').getAttribute('aria-expanded')).toBe('true');
    expect(isHeaderNavMenuOpen()).toBe(true);
    // Bug + profile parked in sheet extras
    expect(document.getElementById('headerNavSheetExtras').contains(document.getElementById('reportBugHeader'))).toBe(true);
    expect(document.getElementById('headerNavSheetExtras').contains(document.getElementById('profileMenuWrap'))).toBe(true);
  });

  it('closes on view-tab click and clears dialog attrs', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: String(query).includes('1023.98'),
      media: String(query),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }));
    initHeaderNavMenu();
    openHeaderNavMenu();

    document.querySelector('.view-tab[data-view="library"]').click();
    const panel = document.getElementById('headerNavPanel');
    expect(panel.hidden).toBe(true);
    expect(panel.hasAttribute('aria-modal')).toBe(false);
    expect(isHeaderNavMenuOpen()).toBe(false);
  });

  it('stays inline on wide desktop when content fits', () => {
    vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: false,
      media: String(query),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }));
    // Make row wide enough for brand + nav + actions in the mocked layout.
    const row = document.querySelector('.app-header-row');
    row.style.width = '1200px';
    document.getElementById('appHeaderNav').style.width = '200px';
    Object.defineProperty(row, 'clientWidth', { configurable: true, get: () => 1200 });
    Object.defineProperty(document.querySelector('.app-header-brand'), 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ width: 100 }),
    });
    Object.defineProperty(document.querySelector('.app-header-actions'), 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ width: 150 }),
    });
    Object.defineProperty(document.getElementById('appHeaderNav'), 'scrollWidth', {
      configurable: true,
      get: () => 200,
    });

    initHeaderNavMenu();
    expect(document.documentElement.classList.contains(headerNavSheetClassForTest())).toBe(false);
    expect(openHeaderNavMenu()).toBe(false);
    expect(document.querySelector('.app-header-actions').contains(document.getElementById('reportBugHeader'))).toBe(true);
  });
});
