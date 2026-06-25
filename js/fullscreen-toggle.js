/** Header control: toggle browser full screen (same result as F11). */

const TV_ICON = `<svg class="header-fullscreen-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><rect x="2.5" y="4" width="19" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="1.75"/><path d="M8.5 21h7" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/><path d="M12 17v4" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/></svg>`;

const EXIT_ICON = `<svg class="header-fullscreen-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M9 4H4v5M15 4h5v5M15 20h5v-5M9 20H4v-5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

export function isFullscreenActive() {
  return Boolean(
    document.fullscreenElement
      || document.webkitFullscreenElement
      || document.msFullscreenElement,
  );
}

export function toggleBrowserFullscreen() {
  if (isFullscreenActive()) {
    const exit = document.exitFullscreen
      || document.webkitExitFullscreen
      || document.msExitFullscreen;
    return exit ? Promise.resolve(exit.call(document)) : Promise.reject(new Error('unsupported'));
  }
  const el = document.documentElement;
  const enter = el.requestFullscreen
    || el.webkitRequestFullscreen
    || el.msRequestFullscreen;
  return enter ? Promise.resolve(enter.call(el)) : Promise.reject(new Error('unsupported'));
}

export function syncFullscreenButton(btn) {
  if (!btn) return;
  const active = isFullscreenActive();
  btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  btn.title = active ? 'Exit full screen (F11)' : 'Full screen (F11)';
  btn.setAttribute('aria-label', btn.title);
  btn.innerHTML = active ? EXIT_ICON : TV_ICON;
}

export function initFullscreenToggle(buttonId = 'headerFullscreenBtn') {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  syncFullscreenButton(btn);
  btn.addEventListener('click', () => {
    toggleBrowserFullscreen().catch(() => {
      /* Browser may block without a user gesture or in unsupported embeds. */
    });
  });
  document.addEventListener('fullscreenchange', () => syncFullscreenButton(btn));
  document.addEventListener('webkitfullscreenchange', () => syncFullscreenButton(btn));
}
