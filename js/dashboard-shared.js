// Shared dashboard constants and tiny utilities. Leaf module.
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { gameKey } from './game-core.js';
import { filterOutHidden } from './personal-storage.js';
import { prefersReducedMotion } from './motion.js';

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

export const DASH_STORE_COLORS = {
  steam: "#ea580c", gog: "#6d28d9", psn: "#003791", epic: "#64748b",
  amazon: "#c2410c", xbox: "#107C10", battlenet: "#148EFF", ubisoft: "#FFD200",
  nintendo: "#E60012", itch: "#fa5c5c", other: "#94a3b8", manual: "#64748b",
};

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
  steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic", amazon: "Amazon",
  xbox: "Xbox", battlenet: "Battle.net", ubisoft: "Ubisoft", nintendo: "Nintendo",
  itch: "itch.io", other: "Other", manual: "Manual",
};

export const HLTB_BUCKETS = [
  { minExclusive: null, maxInclusive: 2, label: "HLTB 0–2h" },
  { minExclusive: 2, maxInclusive: 5, label: "HLTB 2–5h" },
  { minExclusive: 5, maxInclusive: 10, label: "HLTB 5–10h" },
  { minExclusive: 10, maxInclusive: 20, label: "HLTB 10–20h" },
  { minExclusive: 20, maxInclusive: 40, label: "HLTB 20–40h" },
  { minExclusive: 40, maxInclusive: null, label: "HLTB 40h+" },
];

export function animateCount(el, from, to, format, durationMs = 900) {
  if (!el) return;
  if (prefersReducedMotion() || durationMs <= 0 || from === to) {
    el.textContent = format(to);
    return;
  }
  const start = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const ease = t => 1 - Math.pow(1 - t, 3);
  function tick(now) {
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
  return filterOutHidden(state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))));
}
