/** Stat layout prefs for fetcher health dashboard. */
import { statLayoutStorageKey } from '../../profiles.js';

const STAT_LAYOUTS = ['compact', 'landscape'];

export function statLayout() {
  try {
    const v = localStorage.getItem(statLayoutStorageKey());
    return STAT_LAYOUTS.includes(v) ? v : 'compact';
  } catch {
    return 'compact';
  }
}

export function syncStatLayoutToggle() {
  const btn = document.getElementById('fetcherStatLayoutToggle');
  if (!btn) return;
  const layout = statLayout();
  const landscape = layout === 'landscape';
  btn.setAttribute('aria-pressed', landscape ? 'true' : 'false');
  btn.setAttribute(
    'aria-label',
    landscape ? 'Switch to compact layout' : 'Switch to landscape layout',
  );
}
