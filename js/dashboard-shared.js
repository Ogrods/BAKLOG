// Shared dashboard constants and tiny utilities. Leaf module.
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { gameKey } from './game-core.js';
import { filterOutHidden, filterCounted, libraryGamesBase } from './personal-storage.js';
import { prefersReducedMotion } from './motion.js';
import { isPageHidden } from './visibility.js';
import { STORE_BRAND_COLORS } from './store-brand-colors.js';
import { getColorTheme } from './theme.js';

export { STORE_BRAND_COLORS } from './store-brand-colors.js';

export const ITCH_CLASS_LABELS = {
  game: "Games",
  tool: "Tools",
  assets: "Assets",
  comic: "Comics",
  book: "Books",
  soundtrack: "Soundtracks",
  physical_game: "Physical games",
  other: "Other",
};

// Chart-only color overrides: a few canonical brand primaries are too dark to
// read on the dark chart canvases (Steam navy #1b2838, Epic near-black #2f2d2e,
// Ubisoft pure black #000000). Charts use lighter on-brand tints; badges keep
// STORE_BRAND_COLORS (they render on their own colored chips).
export const DASH_STORE_COLORS = {
  ...STORE_BRAND_COLORS,
  steam: '#66c0f4',    // Steam light brand blue (low-visibility-theme fallback)
  epic: '#cfd2d6',     // Epic grayscale identity, lightened for contrast
  ubisoft: '#0098db',  // Ubisoft Connect blue
};

// Steam's real navy (#1b2838) is unreadable on the dark chart canvas, so charts
// use a blue tint. On low-contrast/near-black themes the bright baby blue reads
// best; on the other themes a more on-brand Steam UI blue is used instead.
const STEAM_LOWVIS_COLOR = '#66c0f4';   // bright baby blue
const STEAM_NORMAL_COLOR = '#417a9b';   // Steam UI blue
const STEAM_LOWVIS_THEMES = new Set(['default', 'dark', 'ember']);

/** Resolve a store's chart color, switching Steam by theme readability. */
export function dashStoreColor(store) {
  const key = (store || '').toLowerCase();
  if (key === 'steam') {
    return STEAM_LOWVIS_THEMES.has(getColorTheme()) ? STEAM_LOWVIS_COLOR : STEAM_NORMAL_COLOR;
  }
  return DASH_STORE_COLORS[key] || '#64748b';
}

export const DASH_STATUS_COLORS = {
  backlog: "#ef4444", next: "#38bdf8", playing: "#facc15", unfinished: "#f97316",
  live: "#ec4899", finished: "#22c55e", skip: "#475569", __none__: "#334155",
};

export const DASH_REVIEW_COLORS = {
  "Overwhelmingly Positive": "#22c55e",
  "Very Positive": "#34d399",
  "Mostly Positive": "#86efac",
  "Mixed": "#fbbf24",
  "Mostly Negative": "#f97316",
  "Negative": "#ef4444",
  "Unreviewed": "#475569",
};

export const DASH_STORE_LABELS = {
  steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic", epic_mobile: "Epic Mobile", amazon: "Amazon",
  xbox: "Xbox", battlenet: "Battle.net", ubisoft: "Ubisoft", nintendo: "Nintendo", humble: "Humble", ea: "EA App",
  itch: "itch.io", indiegala: "IndieGala", other: "Other", manual: "Manual",
};

/** Canonical storefront display order (business-card watermark sequence). */
export const STORE_DISPLAY_ORDER = [
  'steam', 'epic', 'gog', 'humble', 'itch', 'indiegala', 'psn', 'xbox',
  'nintendo', 'amazon', 'battlenet', 'ubisoft', 'ea',
];

export function storeDisplayRank(store) {
  const key = (store || '').toLowerCase();
  const idx = STORE_DISPLAY_ORDER.indexOf(key);
  return idx === -1 ? STORE_DISPLAY_ORDER.length : idx;
}

export function sortStoresByDisplayOrder(stores) {
  return [...new Set((stores || []).map(s => (s || '').toLowerCase()).filter(Boolean))]
    .sort((a, b) => storeDisplayRank(a) - storeDisplayRank(b) || a.localeCompare(b));
}

export const HLTB_BUCKETS = [
  { minExclusive: null, maxInclusive: 2, label: "HLTB 0–2h" },
  { minExclusive: 2, maxInclusive: 5, label: "HLTB 2–5h" },
  { minExclusive: 5, maxInclusive: 10, label: "HLTB 5–10h" },
  { minExclusive: 10, maxInclusive: 20, label: "HLTB 10–20h" },
  { minExclusive: 20, maxInclusive: 40, label: "HLTB 20–40h" },
  { minExclusive: 40, maxInclusive: null, label: "HLTB 40h+" },
];

export function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// Gentle sqrt curve: +1 -> ~450ms, scaling up to a 1300ms cap for big imports.
// (+25 ~650ms, +100 ~900ms, +~324 hits the cap.)
export function countUpDurationForDelta(delta) {
  const d = Math.abs(Math.round(delta)) || 0;
  return Math.min(1300, Math.max(450, 400 + 50 * Math.sqrt(d)));
}

// Landing mega-hero ratio adapted for live fetches: popup train spans ~92% of
// the roll so linear count and +1 popups finish together.
export function heroCountRollMs(delta, popupCount) {
  const d = Math.abs(Math.round(delta)) || 1;
  const count = Math.max(0, Math.round(popupCount) || 0);
  const train = (count - 1) * 300 + 500;
  const landingScaled = 600 + Math.sqrt(d) * 280;
  return Math.min(3500, Math.max(train, landingScaled));
}

export function animateCount(el, from, to, format, durationMs = 900, opts = {}) {
  if (!el) return;
  if (isPageHidden()) {
    el.textContent = format(to);
    return;
  }
  if (prefersReducedMotion() || durationMs <= 0 || from === to) {
    el.textContent = format(to);
    return;
  }
  const start = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const ease = opts.linear
    ? (t => t)
    : opts.easeInOut
      ? easeInOutCubic
      : (t => 1 - Math.pow(1 - t, 3));
  function tick(now) {
    if (isPageHidden()) {
      el.textContent = format(to);
      return;
    }
    const elapsed = (now || performance.now()) - start;
    const t = Math.min(1, elapsed / durationMs);
    const v = from + (to - from) * ease(t);
    el.textContent = format(v);
    if (t < 1) requestAnimationFrame(tick);
    else el.textContent = format(to);
  }
  requestAnimationFrame(tick);
}

export function dashboardLibraryGames() {
  return filterCounted(libraryGamesBase());
}
