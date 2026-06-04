// Rotating dashboard spotlight (hero card with auto-fade).
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { escapeAttr, escapeHtml } from './dom-util.js';
import { gameKey, hltbMain, ratingValue, steamAppIdFromGame, spotlightArtCandidates, hasEnoughReviews, combinedPlaytime, parseReleaseForSort, formatDollar } from './game-core.js';
import { getPersonal, filterOutHidden } from './personal-storage.js';
import { getDealInfo, cutBucketClass } from './deals.js';
import { isBarrel, isLeveragePick, getLibrarySnapshot } from './sabermetrics.js';
import { computeSpotlightSuperlatives } from './creative-metrics.js';
import { eyebrowTip, eyebrowVariant } from './metric-tips.js';
import { familyForEyebrow, spreadByFamily } from './stat-families.js';
import { registerPausable } from './visibility.js';

function releasedWithinMonths(g, months) {
  const t = parseReleaseForSort(g.release_date);
  return t > 0 && (Date.now() - t) <= months * 30 * 24 * 60 * 60 * 1000;
}

function isOnSale(g) {
  const d = getDealInfo(g);
  return !!(d && ((d.cut || 0) > 0 || d.isHistoricalLow));
}

const SPOTLIGHT_INTERVAL_MS = 7000;
export const SPOTLIGHT_FADE_MS = 300;
const RECENT_SPOTLIGHT_CAP = 5;
const RECENT_QUOTA = 5;

// Rare "stinker" easter egg: occasionally the spotlight surfaces the
// lowest-rated game in your catalog with a tongue-in-cheek eyebrow. Same rarity
// as the rare boot-loading tip (RARE_CHANCE in js/tips.js).
const STINKER_EYEBROW = 'Rare stinker';

/** Saber superlatives never replace these curated spotlight categories. */
const SABER_PROTECTED_EYEBROWS = new Set([
  'Recently added',
  'Replay',
  'On sale now',
  STINKER_EYEBROW,
  'Co-op campaign',
  'Couch co-op',
  'Almost mastered',
  'Pick back up',
  'Return to',
  'Up next',
  'Clutch deal',
  'Barrel',
  'New release',
  'Long haul',
  'Weekend-sized',
  'Quick win',
  'Top-rated quick pick',
  'Random pick',
]);

let _stinkerChance = 0.02;

/** Test seam: override the stinker easter-egg probability (0 disables it). */
export function setStinkerChanceForTest(chance) {
  _stinkerChance = chance;
}

// "Random pick" / "Dealer's choice" — a wildcard library title pulled uniformly
// at random. Rolls once per pool build and surfaces only occasionally (low
// chance), so it stays a treat rather than a fixture. Only fires for
// non-trivial libraries so single-game/tiny pools stay predictable.
const MIN_LIBRARY_FOR_RANDOM_PICK = 8;
let _randomPickChance = 0.08;

/** Test seam: override the random-pick probability (0 disables, 1 forces it). */
export function setRandomPickChanceForTest(chance) {
  _randomPickChance = chance;
}

/** One uniformly-random library title, skipping skip/live and any excluded keys. */
function pickRandomLibraryGame(eligible, excludeKeys) {
  const candidates = eligible.filter(g => {
    const status = (getPersonal(g).status) || 'backlog';
    if (status === 'skip' || status === 'live') return false;
    return !excludeKeys.has(gameKey(g));
  });
  if (!candidates.length) return null;
  return candidates[Math.floor(Math.random() * candidates.length)];
}

/** Lowest-rated catalog game with a real rating and art (for the stinker egg). */
function pickStinkerGame(eligible) {
  let worst = null;
  let worstRating = Infinity;
  for (const g of eligible) {
    const r = ratingValue(g);
    if (r <= 0) continue;
    if (r < worstRating) {
      worstRating = r;
      worst = g;
    }
  }
  return worst;
}

let _spotlightTimer = null;
let _rotationWanted = false;
let _spotlightFadeTimer = null;
let _spotlightIndex = 0;
let _spotlightPool = [];
let _spotlightCurrentKey = null;

export function getSpotlightPool() { return _spotlightPool; }
export function getSpotlightCurrentKey() { return _spotlightCurrentKey; }
export function setSpotlightCurrentKey(key) { _spotlightCurrentKey = key; }

export function stopSpotlightRotation() {
  if (_spotlightTimer) clearInterval(_spotlightTimer);
  if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
  _spotlightTimer = null;
  _spotlightFadeTimer = null;
  const el = document.getElementById('dashboardSpotlight');
  if (el) el.classList.remove('is-fading');
  // Intentionally NOT clearing _spotlightIndex / _spotlightCurrentKey / _spotlightPool —
  // see stopDashboardRotations / renderDashboardMega for the "preserve across revisits" rule.
}

function poolKeysEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (gameKey(a[i]) !== gameKey(b[i])) return false;
  }
  return true;
}

export function computeRecentSpotlightKeys(games) {
  if (!state.prefs.librarySeenSeeded) return new Set();
  const seen = state.libraryFirstSeenByKey || {};
  const keys = games
    .map(g => ({ key: gameKey(g), at: seen[gameKey(g)] ?? 0 }))
    .filter(e => e.at > 0)
    .sort((a, b) => b.at - a.at)
    .slice(0, RECENT_SPOTLIGHT_CAP)
    .map(e => e.key);
  return new Set(keys);
}

/** Top N library games by first-seen timestamp (for dashboard recents card). */
export function computeRecentAdditions(games, cap = 10) {
  if (!state.prefs.librarySeenSeeded) return [];
  const seen = state.libraryFirstSeenByKey || {};
  return games
    .map(g => ({ g, at: seen[gameKey(g)] ?? 0 }))
    .filter(e => e.at > 0)
    .sort((a, b) => {
      // Newest first. Within a batch (same first-seen timestamp, e.g. a bulk
      // fetch import) rank by rating, then fall back to alphabetical so ties
      // are deterministic even when neither game has a rating yet.
      if (b.at !== a.at) return b.at - a.at;
      const ra = ratingValue(a.g);
      const rb = ratingValue(b.g);
      if (rb !== ra) return rb - ra;
      return (a.g.name || "").localeCompare(b.g.name || "");
    })
    .slice(0, cap)
    .map(e => ({ ...e.g, _addedAt: e.at }));
}

function gameSpotlightReason(g, recentKeys) {
  const rating = ratingValue(g);
  const hltb = hltbMain(g);
  const personal = getPersonal(g);
  const enough = hasEnoughReviews(g);
  const playtime = combinedPlaytime(g);
  const status = personal.status || 'backlog';
  if (status === 'skip' || status === 'live') return null;

  if (recentKeys?.has(gameKey(g))) {
    return { eyebrow: 'Recently added', score: 96, isRecent: true };
  }

  if (status === 'finished') {
    // "Replay" — capped to ~6% of pool in pickSpotlightGames so finished games
    // appear less often than the other categories. Only worth-revisiting
    // titles (well-reviewed, enough sample) qualify.
    if (rating >= 82 && enough) {
      return { eyebrow: 'Replay', score: rating - 25, isReplay: true };
    }
    return null;
  }
  if (!['backlog', 'next', 'playing', 'unfinished'].includes(status)) return null;

  const trophy = g.trophy_progress;
  if ((status === 'playing' || status === 'unfinished') && trophy != null) {
    if (trophy >= 80 && trophy < 100) {
      return { eyebrow: 'Almost mastered', score: rating + 8 };
    }
    if (trophy >= 20 && trophy < 80) {
      return { eyebrow: 'Pick back up', score: rating + 3 };
    }
  }

  if ((status === 'playing' || status === 'unfinished') && playtime >= 30 && rating >= 70) {
    return { eyebrow: 'Return to', score: rating + 6 };
  }
  if (status === 'next' && rating >= 70) {
    return { eyebrow: 'Up next', score: rating + 10 };
  }
  if (isLeveragePick(g)) {
    return { eyebrow: 'Clutch deal', score: rating + 12, isLeverage: true };
  }
  if (isBarrel(g)) {
    return { eyebrow: 'Barrel', score: rating + 6, isBarrel: true };
  }
  // "On sale now" is intentionally NOT tagged for library games — a discount on
  // something you already own isn't actionable. The category is sourced from the
  // wishlist instead (see wishlist on-sale injection in pickSpotlightGames).
  if (releasedWithinMonths(g, 12) && rating >= 70) {
    return { eyebrow: 'New release', score: rating + 7 };
  }
  if (g.coop_online && rating >= 72 && enough) {
    return { eyebrow: 'Co-op campaign', score: rating + 5 };
  }
  if (g.coop_local && rating >= 70) {
    return { eyebrow: 'Couch co-op', score: rating + 4 };
  }
  if (hltb && hltb >= 40 && rating >= 80 && enough) {
    return { eyebrow: 'Long haul', score: rating + 1 };
  }
  if (rating >= 88 && enough && hltb && hltb <= 8) {
    return { eyebrow: 'Top-rated quick pick', score: rating + 8 };
  }
  if (rating >= 90 && enough) {
    return { eyebrow: 'Critically acclaimed', score: rating + 4 };
  }
  if (rating >= 78 && hltb && hltb <= 5) {
    return { eyebrow: 'Quick win', score: rating + 2 };
  }
  if (rating >= 82 && enough) {
    return { eyebrow: 'Highly rated', score: rating };
  }
  if (rating >= 80 && !enough) {
    return { eyebrow: 'Hidden gem', score: rating - 3 };
  }
  if (rating >= 75 && enough) {
    return { eyebrow: 'Solid pick', score: rating - 5 };
  }
  if (hltb && hltb >= 8 && hltb <= 15 && rating >= 72) {
    return { eyebrow: 'Weekend-sized', score: rating - 4 };
  }
  if (hltb && hltb <= 4 && rating > 0) {
    return { eyebrow: 'Fast finish', score: rating - 6 };
  }
  if (rating >= 70) {
    return { eyebrow: 'Worth a look', score: rating - 10 };
  }
  return null;
}

export function pickSpotlightGames(games) {
  const recentKeys = computeRecentSpotlightKeys(games);
  const failed = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const hasArt = g => {
    if (failed.has(gameKey(g))) return false;
    if (g.header_image || g.library_image) return true;
    return steamAppIdFromGame(g) != null;
  };
  const eligible = games.filter(hasArt);
  const target = Math.max(60, Math.round(eligible.length * 0.35));

  const tagged = [];
  for (const g of eligible) {
    const reason = gameSpotlightReason(g, recentKeys);
    if (reason) tagged.push({ g, reason });
  }

  // "On sale now" is sourced exclusively from the wishlist: surface discounts on
  // games you want but don't own yet. Mirrors the visible-wishlist filter used by
  // the deal radar (cross-store-hidden + user-hidden excluded).
  const wlHidden = state.wishlistCrossStoreHiddenKeys || new Set();
  const wishlistOnSale = filterOutHidden(
    (state.wishlistGames || []).filter(g => !wlHidden.has(gameKey(g)))
  )
    .filter(hasArt)
    .filter(g => isOnSale(g) && ratingValue(g) >= 70)
    .map(g => {
      const deal = getDealInfo(g);
      const cut = deal?.cut || 0;
      const rating = ratingValue(g);
      const metaParts = [`<strong>${rating}%</strong> review`];
      if (cut > 0) {
        metaParts.push(`<strong class="dash-spotlight-cut ${cutBucketClass(cut)}">-${cut}%</strong> off`);
      }
      if (deal?.price != null) {
        metaParts.push(`<strong class="dash-spotlight-price ${cutBucketClass(cut)}">${escapeHtml(formatDollar(deal.price))}</strong>`);
      }
      return {
        g,
        reason: {
          eyebrow: 'On sale now',
          score: rating + 9,
          isWishlistSale: true,
          metaParts,
        },
      };
    });
  tagged.push(...wishlistOnSale);

  const snap = getLibrarySnapshot(games);
  const saberPicks = computeSpotlightSuperlatives(eligible, snap);

  const saberByKey = new Map();
  for (const pick of saberPicks) {
    const prev = saberByKey.get(pick.key);
    if (!prev || pick.score >= prev.score) saberByKey.set(pick.key, pick);
  }
  for (const pick of saberByKey.values()) {
    const g = eligible.find(x => gameKey(x) === pick.key);
    if (!g) continue;
    const reason = {
      eyebrow: pick.eyebrow,
      score: pick.score,
      metaParts: pick.metaParts,
      isSaber: true,
    };
    const idx = tagged.findIndex(t => gameKey(t.g) === pick.key);
    if (idx >= 0) {
      const existing = tagged[idx].reason;
      if (SABER_PROTECTED_EYEBROWS.has(existing.eyebrow)) continue;
      if (pick.score >= existing.score) tagged[idx].reason = reason;
    } else {
      tagged.push({ g, reason });
    }
  }

  tagged.sort((a, b) => b.reason.score - a.reason.score);
  const top = tagged.slice(0, target);

  const recentQuota = Math.min(RECENT_QUOTA, recentKeys.size);
  const recentsInTop = top.filter(t => t.reason.isRecent).length;
  if (recentsInTop > recentQuota) {
    let toDrop = recentsInTop - recentQuota;
    for (let i = top.length - 1; i >= 0 && toDrop > 0; i--) {
      if (top[i].reason.isRecent) {
        top.splice(i, 1);
        toDrop--;
      }
    }
  } else if (recentsInTop < recentQuota) {
    const extras = tagged.slice(target).filter(t => t.reason.isRecent);
    const need = Math.min(recentQuota - recentsInTop, extras.length);
    for (let i = 0; i < need; i++) top.push(extras[i]);
  }

  // Cap "Replay" entries at ~3.5% so finished games appear noticeably less often
  // than the other rotating categories. If the natural sort overshoots, drop
  // the lowest-scoring replays; if it undershoots, pull in additional replay
  // candidates that fell outside the score cutoff so the category still
  // surfaces (minimum of 1) in libraries with lots of high-rated finished
  // games.
  const REPLAY_RATIO = 0.035;
  const replayQuota = Math.max(1, Math.round(top.length * REPLAY_RATIO));
  const replaysInTop = top.filter(t => t.reason.isReplay).length;
  if (replaysInTop > replayQuota) {
    let toDrop = replaysInTop - replayQuota;
    for (let i = top.length - 1; i >= 0 && toDrop > 0; i--) {
      if (top[i].reason.isReplay) {
        top.splice(i, 1);
        toDrop--;
      }
    }
  } else if (replaysInTop < replayQuota) {
    const extras = tagged.slice(target).filter(t => t.reason.isReplay);
    const need = Math.min(replayQuota - replaysInTop, extras.length);
    for (let i = 0; i < need; i++) top.push(extras[i]);
  }

  const BARREL_RATIO = 0.04;
  const barrelQuota = Math.max(1, Math.round(top.length * BARREL_RATIO));
  let barrelsInTop = top.filter(t => t.reason.isBarrel);
  if (barrelsInTop.length > barrelQuota) {
    barrelsInTop.sort((a, b) => a.reason.score - b.reason.score);
    const dropKeys = new Set(
      barrelsInTop.slice(0, barrelsInTop.length - barrelQuota).map(t => gameKey(t.g)),
    );
    for (let i = top.length - 1; i >= 0; i--) {
      if (dropKeys.has(gameKey(top[i].g))) top.splice(i, 1);
    }
  }

  for (let i = top.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [top[i], top[j]] = [top[j], top[i]];
  }
  const spreadTop = spreadByFamily(top, t => familyForEyebrow(t.reason.eyebrow), { wrap: true });
  const pool = spreadTop.map(({ g, reason }) => Object.assign({}, g, { _spotlightReason: reason }));

  // "Random pick" wildcard: surface one library title at random (it may not have
  // earned any other category). Kept clear of the quota'd categories
  // (recents / replay / barrel) so it never eats their guaranteed slots, and
  // de-clustered as its own family so it never reads as a duplicate of a neighbor.
  if (eligible.length >= MIN_LIBRARY_FOR_RANDOM_PICK && Math.random() < _randomPickChance) {
    const protectedKeys = new Set(
      pool
        .filter(g => g._spotlightReason?.isRecent || g._spotlightReason?.isReplay || g._spotlightReason?.isBarrel)
        .map(gameKey),
    );
    const randomPick = pickRandomLibraryGame(eligible, protectedKeys);
    if (randomPick) {
      const key = gameKey(randomPick);
      const at = pool.findIndex(g => gameKey(g) === key);
      if (at >= 0) pool.splice(at, 1);
      const entry = Object.assign({}, randomPick, {
        _spotlightReason: { eyebrow: 'Random pick', score: 50, isRandom: true },
      });
      const insertAt = Math.floor(Math.random() * (pool.length + 1));
      pool.splice(insertAt, 0, entry);
    }
  }

  // Preserve the previously-displayed game across dashboard revisits: if it's still
  // eligible, rotate it to index 0 so re-paint doesn't visibly switch games.
  if (_spotlightCurrentKey) {
    const idx = pool.findIndex(g => gameKey(g) === _spotlightCurrentKey);
    if (idx > 0) {
      const [head] = pool.splice(idx, 1);
      pool.unshift(head);
    }
  }

  // Rare stinker easter egg: roll once per pool build and, when it hits, drop the
  // lowest-rated catalog game at the front so it actually shows this render.
  if (Math.random() < _stinkerChance) {
    const stinker = pickStinkerGame(eligible);
    if (stinker) {
      const key = gameKey(stinker);
      const at = pool.findIndex(g => gameKey(g) === key);
      if (at >= 0) pool.splice(at, 1);
      pool.unshift(Object.assign({}, stinker, {
        _spotlightReason: { eyebrow: STINKER_EYEBROW, score: 999, isStinker: true },
      }));
    }
  }
  return pool;
}

const SPOTLIGHT_STATUS_LABEL = {
  backlog: 'in backlog',
  next: 'next up',
  playing: 'in progress',
  unfinished: 'unfinished',
  finished: 'completed',
};

function spotlightJumpDest(g) {
  return g.store === 'wishlist' ? 'wishlist' : g.store === 'itch' ? 'itch.io' : 'library';
}

export function spotlightInnerHtml(g) {
  const candidates = spotlightArtCandidates(g);
  const art = candidates[0] || "";
  const candidateAttr = escapeAttr(candidates.join("|"));
  const rating = ratingValue(g);
  const hltb = hltbMain(g);
  const hltbStr = hltb != null ? `${Math.round(hltb)}h` : '?';
  const status = (getPersonal(g).status) || 'backlog';
  const statusLabel = g.store === 'wishlist'
    ? 'on your wishlist'
    : (SPOTLIGHT_STATUS_LABEL[status] || 'in your library');
  const eyebrow = g._spotlightReason?.eyebrow || 'Spotlight';
  const displayEyebrow = eyebrowVariant(eyebrow, gameKey(g));
  const eyebrowTipText = eyebrowTip(eyebrow);
  const eyebrowTitleAttr = eyebrowTipText ? ` title="${escapeAttr(eyebrowTipText)}"` : '';
  const customMeta = g._spotlightReason?.metaParts;
  const metaParts = customMeta?.length
    ? customMeta
    : [
      `<strong>${rating}%</strong> review`,
      `<strong>${escapeHtml(hltbStr)}</strong> main`,
      escapeHtml(statusLabel),
    ];
  return `
    <img class="dash-spotlight-art-bg" alt="" aria-hidden="true" />
    <img class="dash-spotlight-art" src="${escapeAttr(art)}" alt="" loading="lazy" data-spotlight-candidates="${candidateAttr}" data-spotlight-idx="0" onload="this.classList.add('is-loaded');window.applySpotlightArtFit(this)" onerror="window.spotlightArtFallback(this)" />
    <div class="dash-spotlight-sheen" aria-hidden="true"></div>
    <div class="dash-spotlight-gradient" aria-hidden="true"></div>
    <div class="dash-spotlight-body">
      <span class="dash-spotlight-eyebrow"${eyebrowTitleAttr}>${escapeHtml(displayEyebrow)}</span>
      <span class="dash-spotlight-title">${escapeHtml(g.name)}</span>
      <span class="dash-spotlight-meta">${metaParts.join(' · ')}</span>
    </div>
    <span class="dash-spotlight-nav" aria-hidden="false">
      <span class="dash-spotlight-nav-btn" role="button" tabindex="0" data-spotlight-nav="prev" aria-label="Previous spotlight" title="Previous">‹</span>
      <span class="dash-spotlight-nav-btn" role="button" tabindex="0" data-spotlight-nav="next" aria-label="Next spotlight" title="Next">›</span>
    </span>`;
}

export function renderSpotlightHtml(g) {
  const key = gameKey(g);
  return `
    <button type="button" class="dash-spotlight" id="dashboardSpotlight" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in ${escapeAttr(spotlightJumpDest(g))}">
      ${spotlightInnerHtml(g)}
    </button>`;
}

export function primeSpotlightArt(btn) {
  const img = btn?.querySelector('.dash-spotlight-art');
  if (!img) return;
  if (img.complete && img.naturalWidth > 0) {
    img.classList.add('is-loaded');
    window.applySpotlightArtFit?.(img);
  }
}

function applySpotlightSlide(el, next) {
  el.classList.remove('has-portrait-art');
  el.innerHTML = spotlightInnerHtml(next);
  el.dataset.key = gameKey(next);
  el.title = `Jump to ${next.name} in ${spotlightJumpDest(next)}`;
  el.classList.remove('is-fading');
  primeSpotlightArt(el);
  _spotlightCurrentKey = gameKey(next);
}

function fadeToSpotlight(el, next) {
  el.classList.add('is-fading');
  if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
  _spotlightFadeTimer = setTimeout(() => {
    applySpotlightSlide(el, next);
    _spotlightFadeTimer = null;
  }, SPOTLIGHT_FADE_MS);
}

function stopSpotlightTimer() {
  if (_spotlightTimer) clearInterval(_spotlightTimer);
  _spotlightTimer = null;
}

function startSpotlightTimer(el) {
  stopSpotlightTimer();
  _spotlightTimer = setInterval(() => {
    const paused = el._spotlightPaused?.() ?? false;
    if (paused) return;
    if (!document.getElementById('dashboardSpotlight')) {
      stopSpotlightRotation();
      return;
    }
    _spotlightIndex = (_spotlightIndex + 1) % _spotlightPool.length;
    fadeToSpotlight(el, _spotlightPool[_spotlightIndex]);
  }, SPOTLIGHT_INTERVAL_MS);
}

function wireSpotlightHover(el) {
  if (!el || el.dataset.hoverWired) return;
  el.dataset.hoverWired = '1';
  let paused = false;
  el.addEventListener('mouseenter', () => { paused = true; });
  el.addEventListener('mouseleave', () => { paused = false; });
  el._spotlightPaused = () => paused;

  el.addEventListener('click', (e) => {
    const nav = e.target.closest('[data-spotlight-nav]');
    if (!nav) return;
    e.preventDefault();
    e.stopPropagation();
    stepSpotlight(nav.dataset.spotlightNav === 'prev' ? -1 : 1);
  });

  el.addEventListener('keydown', (e) => {
    const nav = e.target.closest('[data-spotlight-nav]');
    if (nav && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      e.stopPropagation();
      stepSpotlight(nav.dataset.spotlightNav === 'prev' ? -1 : 1);
      return;
    }
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      e.stopPropagation();
      stepSpotlight(-1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      stepSpotlight(1);
    }
  });
}

export function stepSpotlight(delta) {
  if (_spotlightPool.length <= 1) return;
  const el = document.getElementById('dashboardSpotlight');
  if (!el) return;
  const len = _spotlightPool.length;
  _spotlightIndex = (_spotlightIndex + delta + len) % len;
  fadeToSpotlight(el, _spotlightPool[_spotlightIndex]);
  if (_rotationWanted) {
    stopSpotlightTimer();
    startSpotlightTimer(el);
  }
}

export function startSpotlightRotation(pool) {
  const el = document.getElementById('dashboardSpotlight');
  if (el) {
    if (pool && pool.length > 1) el.classList.add('dash-spotlight--multi');
    else el.classList.remove('dash-spotlight--multi');
  }
  if (!pool || pool.length <= 1) {
    stopSpotlightRotation();
    _spotlightPool = pool || [];
    _rotationWanted = false;
    return;
  }
  _rotationWanted = true;
  if (!el) return;
  const domMatches = !!pool[0] && el.dataset.key === gameKey(pool[0]);
  _spotlightPool = pool;
  wireSpotlightHover(el);
  // Same slide still mounted: resume rotation only (no innerHTML swap / fade-in).
  if (domMatches) {
    if (_spotlightTimer) return;
    startSpotlightTimer(el);
    return;
  }
  stopSpotlightRotation();
  // _spotlightIndex is intentionally NOT reset — pickSpotlightGames has already
  // arranged the pool so the previously-displayed game is at index 0; on first
  // load _spotlightIndex is already 0 from module init.
  _spotlightIndex = 0;
  startSpotlightTimer(el);
}

export function syncSpotlightInMega(el, spotlight) {
  const hero = el.querySelector('.dash-mega-hero');
  const existing = document.getElementById('dashboardSpotlight');
  const newKey = spotlight ? gameKey(spotlight) : null;
  if (spotlight && existing?.dataset.key === newKey) {
    primeSpotlightArt(existing);
    return;
  }
  if (spotlight && existing) {
    stopSpotlightRotation();
    existing.outerHTML = renderSpotlightHtml(spotlight);
    primeSpotlightArt(document.getElementById('dashboardSpotlight'));
    return;
  }
  if (spotlight && !existing && hero) {
    hero.insertAdjacentHTML('afterbegin', renderSpotlightHtml(spotlight));
    primeSpotlightArt(document.getElementById('dashboardSpotlight'));
    return;
  }
  existing?.remove();
}

if (typeof document !== 'undefined') {
  registerPausable({
    pause: stopSpotlightRotation,
    resume() {
      if (_rotationWanted && _spotlightPool.length > 1) {
        startSpotlightRotation(_spotlightPool);
      }
    },
  });
}
