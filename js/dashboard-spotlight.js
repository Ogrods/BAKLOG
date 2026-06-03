// Rotating dashboard spotlight (hero card with auto-fade).
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { escapeAttr, escapeHtml } from './dom-util.js';
import { gameKey, hltbMain, ratingValue, coverFallbackFor, libraryCoverFor, sanitizeCoverUrl, hasEnoughReviews, combinedPlaytime, parseReleaseForSort } from './game-core.js';
import { getPersonal, filterOutHidden } from './personal-storage.js';
import { getDealInfo } from './deals.js';

function releasedWithinMonths(g, months) {
  const t = parseReleaseForSort(g.release_date);
  return t > 0 && (Date.now() - t) <= months * 30 * 24 * 60 * 60 * 1000;
}

function isOnSale(g) {
  const d = getDealInfo(g);
  return !!(d && ((d.cut || 0) > 0 || d.isHistoricalLow));
}

const SPOTLIGHT_INTERVAL_MS = 7000;
const SPOTLIGHT_FADE_MS = 300;
const RECENT_SPOTLIGHT_CAP = 5;
const RECENT_QUOTA = 5;

let _spotlightTimer = null;
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
  const hasArt = g => !!(g.header_image || g.library_image) && !failed.has(gameKey(g));
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
    .map(g => ({ g, reason: { eyebrow: 'On sale now', score: ratingValue(g) + 9, isWishlistSale: true } }));
  tagged.push(...wishlistOnSale);

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

  for (let i = top.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [top[i], top[j]] = [top[j], top[i]];
  }
  const pool = top.map(({ g, reason }) => Object.assign({}, g, { _spotlightReason: reason }));

  // Preserve the previously-displayed game across dashboard revisits: if it's still
  // eligible, rotate it to index 0 so re-paint doesn't visibly switch games.
  if (_spotlightCurrentKey) {
    const idx = pool.findIndex(g => gameKey(g) === _spotlightCurrentKey);
    if (idx > 0) {
      const [head] = pool.splice(idx, 1);
      pool.unshift(head);
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
  const art = sanitizeCoverUrl(g.header_image) || libraryCoverFor(g);
  const rating = ratingValue(g);
  const hltb = hltbMain(g);
  const hltbStr = hltb != null ? `${Math.round(hltb)}h` : '?';
  const status = (getPersonal(g).status) || 'backlog';
  const statusLabel = g.store === 'wishlist'
    ? 'on your wishlist'
    : (SPOTLIGHT_STATUS_LABEL[status] || 'in your library');
  const eyebrow = g._spotlightReason?.eyebrow || 'Spotlight';
  return `
    <img class="dash-spotlight-art" src="${escapeAttr(art)}" alt="" loading="lazy" onload="this.classList.add('is-loaded')" onerror="this.classList.add('is-loaded');window.coverFallback(this)" />
    <div class="dash-spotlight-gradient" aria-hidden="true"></div>
    <div class="dash-spotlight-body">
      <span class="dash-spotlight-eyebrow">${escapeHtml(eyebrow)}</span>
      <span class="dash-spotlight-title">${escapeHtml(g.name)}</span>
      <span class="dash-spotlight-meta"><strong>${rating}%</strong> review · <strong>${escapeHtml(hltbStr)}</strong> main · ${escapeHtml(statusLabel)}</span>
    </div>`;
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
  if (img.complete && img.naturalWidth > 0) img.classList.add('is-loaded');
}

function wireSpotlightHover(el) {
  if (!el || el.dataset.hoverWired) return;
  el.dataset.hoverWired = '1';
  let paused = false;
  el.addEventListener('mouseenter', () => { paused = true; });
  el.addEventListener('mouseleave', () => { paused = false; });
  el._spotlightPaused = () => paused;
}

export function startSpotlightRotation(pool) {
  if (!pool || pool.length <= 1) {
    stopSpotlightRotation();
    _spotlightPool = pool || [];
    return;
  }
  const el = document.getElementById('dashboardSpotlight');
  if (!el) return;
  const domMatches = !!pool[0] && el.dataset.key === gameKey(pool[0]);
  _spotlightPool = pool;
  // Same slide still mounted: resume rotation only (no innerHTML swap / fade-in).
  if (domMatches) {
    if (_spotlightTimer) return;
    wireSpotlightHover(el);
    _spotlightTimer = setInterval(() => {
      const paused = el._spotlightPaused?.() ?? false;
      if (paused) return;
      if (!document.getElementById('dashboardSpotlight')) {
        stopSpotlightRotation();
        return;
      }
      _spotlightIndex = (_spotlightIndex + 1) % _spotlightPool.length;
      const next = _spotlightPool[_spotlightIndex];
      el.classList.add('is-fading');
      if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
      _spotlightFadeTimer = setTimeout(() => {
        el.innerHTML = spotlightInnerHtml(next);
        el.dataset.key = gameKey(next);
        el.title = `Jump to ${next.name} in ${spotlightJumpDest(next)}`;
        el.classList.remove('is-fading');
        primeSpotlightArt(el);
        _spotlightCurrentKey = gameKey(next);
      }, SPOTLIGHT_FADE_MS);
    }, SPOTLIGHT_INTERVAL_MS);
    return;
  }
  stopSpotlightRotation();
  // _spotlightIndex is intentionally NOT reset — pickSpotlightGames has already
  // arranged the pool so the previously-displayed game is at index 0; on first
  // load _spotlightIndex is already 0 from module init.
  _spotlightIndex = 0;
  wireSpotlightHover(el);
  _spotlightTimer = setInterval(() => {
    if (el._spotlightPaused?.()) return;
    if (!document.getElementById('dashboardSpotlight')) {
      stopSpotlightRotation();
      return;
    }
    _spotlightIndex = (_spotlightIndex + 1) % _spotlightPool.length;
    const next = _spotlightPool[_spotlightIndex];
    el.classList.add('is-fading');
    if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
    _spotlightFadeTimer = setTimeout(() => {
      el.innerHTML = spotlightInnerHtml(next);
      el.dataset.key = gameKey(next);
      el.title = `Jump to ${next.name} in ${spotlightJumpDest(next)}`;
      el.classList.remove('is-fading');
      primeSpotlightArt(el);
      _spotlightCurrentKey = gameKey(next);
    }, SPOTLIGHT_FADE_MS);
  }, SPOTLIGHT_INTERVAL_MS);
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
