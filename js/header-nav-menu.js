/**
 * Main-view hamburger: collapses header tabs into a left sheet when the
 * tablet ladder matches OR the inline header would wrap (fit check).
 * Sheet also hosts Report bug + profile; fullscreen is CSS-hidden.
 */
import { bindEscapeClose, trapFocus } from './focus-trap.js';

const TABLET_MQ = '(max-width: 1023.98px)';
const SHEET_CLASS = 'header-nav-sheet';

let releaseTrap = null;
let releaseEsc = null;
let fitRaf = 0;

function isTabletMq() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(TABLET_MQ).matches;
}

function isSheetMode() {
  return document.documentElement.classList.contains(SHEET_CLASS);
}

function els() {
  return {
    toggle: document.getElementById('headerNavToggle'),
    backdrop: document.getElementById('headerNavBackdrop'),
    panel: document.getElementById('headerNavPanel'),
    wrap: document.getElementById('appHeaderNavWrap'),
    extras: document.getElementById('headerNavSheetExtras'),
    actions: document.querySelector('.app-header-actions'),
    row: document.querySelector('.app-header-row'),
    brand: document.querySelector('.app-header-brand'),
    nav: document.getElementById('appHeaderNav'),
    reportBug: document.getElementById('reportBugHeader'),
    profileWrap: document.getElementById('profileMenuWrap'),
    fullscreen: document.getElementById('headerFullscreenBtn'),
  };
}

/** Put bug + profile back in the header actions (after fullscreen). */
function parkExtrasInActions() {
  const { actions, extras, reportBug, profileWrap, fullscreen } = els();
  if (!actions) return;
  const anchor = fullscreen?.nextSibling ?? null;
  if (reportBug && reportBug.parentElement !== actions) {
    actions.insertBefore(reportBug, anchor);
  }
  if (profileWrap && profileWrap.parentElement !== actions) {
    actions.appendChild(profileWrap);
  }
  if (extras) extras.hidden = true;
}

/** Move bug + profile into the sheet footer. */
function parkExtrasInSheet() {
  const { extras, reportBug, profileWrap } = els();
  if (!extras) return;
  if (reportBug) extras.appendChild(reportBug);
  if (profileWrap) extras.appendChild(profileWrap);
  extras.hidden = false;
}

export function isHeaderNavMenuOpen() {
  const { panel } = els();
  return !!(panel && !panel.hidden && panel.getAttribute('aria-modal') === 'true');
}

export function closeHeaderNavMenu() {
  const { toggle, backdrop, panel, wrap } = els();
  releaseTrap?.();
  releaseTrap = null;
  releaseEsc?.();
  releaseEsc = null;
  if (backdrop) backdrop.hidden = true;
  if (panel) {
    panel.hidden = isSheetMode();
    panel.removeAttribute('role');
    panel.removeAttribute('aria-modal');
    panel.removeAttribute('aria-label');
  }
  wrap?.classList.remove('is-open');
  if (toggle) {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open menu');
    toggle.title = 'Menu';
  }
}

export function openHeaderNavMenu() {
  if (!isSheetMode()) return false;
  const { toggle, backdrop, panel, wrap } = els();
  if (!panel || !toggle) return false;
  if (backdrop) backdrop.hidden = false;
  panel.hidden = false;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', 'Main menu');
  wrap?.classList.add('is-open');
  toggle.setAttribute('aria-expanded', 'true');
  toggle.setAttribute('aria-label', 'Close menu');
  toggle.title = 'Close menu';
  releaseTrap?.();
  releaseEsc?.();
  releaseTrap = trapFocus(panel);
  releaseEsc = bindEscapeClose(panel, closeHeaderNavMenu);
  const active = panel.querySelector('.view-tab.active') || panel.querySelector('.view-tab');
  active?.focus({ preventScroll: true });
  return true;
}

export function toggleHeaderNavMenu() {
  if (isHeaderNavMenuOpen()) closeHeaderNavMenu();
  else openHeaderNavMenu();
}

/**
 * Measure whether brand + inline tabs + actions fit on one row.
 * Temporarily forces inline layout for an accurate width check.
 */
function measureNeedsSheet() {
  if (isTabletMq()) return true;
  const { row, brand, nav, actions, toggle, panel } = els();
  if (!row || !brand || !nav || !actions) return isTabletMq();

  const wasOpen = isHeaderNavMenuOpen();
  if (wasOpen) closeHeaderNavMenu();

  const html = document.documentElement;
  const wasSheet = html.classList.contains(SHEET_CLASS);
  parkExtrasInActions();
  html.classList.remove(SHEET_CLASS);

  const prevToggleHidden = toggle?.hidden;
  const prevPanelHidden = panel?.hidden;
  if (toggle) toggle.hidden = true;
  if (panel) panel.hidden = false;

  void row.offsetWidth;
  const styles = getComputedStyle(row);
  const gapX = parseFloat(styles.columnGap || styles.gap || '0') || 0;
  // Two gaps between three flex children (brand | nav | actions).
  const need =
    brand.getBoundingClientRect().width
    + nav.scrollWidth
    + actions.getBoundingClientRect().width
    + gapX * 2;
  const avail = row.clientWidth;

  if (toggle) toggle.hidden = prevToggleHidden ?? true;
  if (panel && prevPanelHidden != null) panel.hidden = prevPanelHidden;
  if (wasSheet) html.classList.add(SHEET_CLASS);

  // Hysteresis so resize does not flap between inline and sheet.
  if (wasSheet) return need > avail - 24;
  return need > avail + 1;
}

function applySheetMode(on) {
  const html = document.documentElement;
  const { panel, toggle } = els();
  const wasOpen = isHeaderNavMenuOpen();

  if (on) {
    html.classList.add(SHEET_CLASS);
    parkExtrasInSheet();
    if (toggle) toggle.hidden = false;
    if (!wasOpen && panel) {
      panel.hidden = true;
      panel.removeAttribute('role');
      panel.removeAttribute('aria-modal');
      panel.removeAttribute('aria-label');
    }
  } else {
    if (wasOpen) closeHeaderNavMenu();
    parkExtrasInActions();
    html.classList.remove(SHEET_CLASS);
    if (panel) {
      panel.hidden = false;
      panel.removeAttribute('role');
      panel.removeAttribute('aria-modal');
      panel.removeAttribute('aria-label');
    }
    if (toggle) {
      toggle.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open menu');
    }
  }
}

function syncSheetMode() {
  applySheetMode(measureNeedsSheet());
}

function scheduleFitSync() {
  if (fitRaf) cancelAnimationFrame(fitRaf);
  fitRaf = requestAnimationFrame(() => {
    fitRaf = 0;
    syncSheetMode();
  });
}

export function initHeaderNavMenu() {
  const { toggle, backdrop, panel } = els();
  if (!toggle || !panel) return;

  toggle.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleHeaderNavMenu();
  });
  backdrop?.addEventListener('click', () => closeHeaderNavMenu());
  panel.addEventListener('click', (e) => {
    if (e.target.closest('.view-tab')) closeHeaderNavMenu();
  });

  syncSheetMode();

  window.addEventListener('resize', scheduleFitSync, { passive: true });
  if (typeof ResizeObserver === 'function') {
    const row = document.querySelector('.app-header-row');
    if (row) {
      const ro = new ResizeObserver(() => scheduleFitSync());
      ro.observe(row);
    }
  }
  if (typeof window.matchMedia === 'function') {
    const mq = window.matchMedia(TABLET_MQ);
    const onChange = () => scheduleFitSync();
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else mq.addListener(onChange);
  }
}

/** @internal Vitest */
export function headerNavSheetClassForTest() {
  return SHEET_CLASS;
}
