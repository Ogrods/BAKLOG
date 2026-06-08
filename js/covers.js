// Window-level cover helpers. Inline `onload`/`onerror` handlers in row HTML
// reach these via `window.coverFallback` / `window.markLandscape`, so this
// module installs them on import (side effect) and also exports
// `syncCoverFits` for callers that need to re-prime cached images.

import { sanitizeCoverUrl, spotlightCropForAspect } from "./game-core.js";

const DASH_FAILED_COVERS_KEY = "baklog-dash-failed-covers";
window.__dashFailedCovers = window.__dashFailedCovers || (() => {
  try {
    const stored = JSON.parse(localStorage.getItem(DASH_FAILED_COVERS_KEY) || "[]");
    return new Set(Array.isArray(stored) ? stored : []);
  } catch { return new Set(); }
})();
let _dashFailedSaveTimer = 0;
function persistDashFailedCovers() {
  if (_dashFailedSaveTimer) return;
  _dashFailedSaveTimer = setTimeout(() => {
    _dashFailedSaveTimer = 0;
    try {
      localStorage.setItem(
        DASH_FAILED_COVERS_KEY,
        JSON.stringify([...window.__dashFailedCovers].slice(-2000)),
      );
    } catch {}
  }, 800);
}
window.coverFallback = function (img) {
  const sslRetry = sanitizeCoverUrl(img.src);
  if (sslRetry && sslRetry !== img.src && !img.dataset.sslRetried) {
    img.dataset.sslRetried = "1";
    img.src = sslRetry;
    return;
  }
  const fb = sanitizeCoverUrl(img.dataset.fallback);
  if (fb && img.src !== fb) {
    img.src = fb;
    img.dataset.fallback = "";
    return;
  }
  // Recently-added rows keep a stable count (up to 10), so a failed cover must
  // not collapse the row — that's what produced the "top + bottom only" gap.
  // Swap the broken <img> for a compact initials placeholder and leave the row.
  const recentRow = img.closest(".dash-recent-row");
  if (recentRow) {
    const rName = img.dataset.name || "";
    const rWords = rName.split(/\s+/).filter(Boolean);
    const rInitials = (rWords.slice(0, 3).map(w => w[0]).join("") || "?").toUpperCase().slice(0, 3);
    const rSafe = rName.replace(/"/g, "&quot;");
    img.outerHTML = `<div class="dash-list-cover placeholder" title="${rSafe}"><span class="placeholder-initials">${rInitials}</span></div>`;
    return;
  }
  const dashRow = img.closest(".dash-versus-row, .dash-list-row, .coop-pick-row, .itch-hero-card");
  if (dashRow) {
    const key = dashRow.dataset.key || dashRow.dataset.gameKey;
    if (key && !window.__dashFailedCovers.has(key)) {
      window.__dashFailedCovers.add(key);
      persistDashFailedCovers();
    }
    dashRow.style.display = "none";
    return;
  }
  const name = img.dataset.name || "";
  const cls = img.classList.contains("pick-cover") ? "pick-cover placeholder" : "cover placeholder";
  const words = name.split(/\s+/).filter(Boolean);
  const initials = (words.slice(0, 3).map(w => w[0]).join("") || "?").toUpperCase().slice(0, 3);
  const captionRaw = words.slice(0, 4).join(" ").slice(0, 28);
  const safeName = name.replace(/"/g, "&quot;");
  const safeCap = captionRaw.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  img.outerHTML = `<div class="${cls}" title="${safeName}"><span class="placeholder-initials">${initials}</span><span class="placeholder-caption">${safeCap}</span></div>`;
};
const LANDSCAPE_CACHE_KEY = "baklog-landscape-covers";
window.__landscapeCovers = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(LANDSCAPE_CACHE_KEY) || "[]")); }
  catch { return new Set(); }
})();
let _landscapeSaveTimer = 0;
function persistLandscapeCache() {
  if (_landscapeSaveTimer) return;
  _landscapeSaveTimer = setTimeout(() => {
    _landscapeSaveTimer = 0;
    try { localStorage.setItem(LANDSCAPE_CACHE_KEY, JSON.stringify([...window.__landscapeCovers].slice(-1500))); } catch {}
  }, 800);
}
window.coverLandscapeAttr = function (url) {
  return url && window.__landscapeCovers.has(url) ? " landscape" : "";
};
const PORTRAIT_ANIM_CLASSES = ["portrait-anim-1", "portrait-anim-2", "portrait-anim-3", "portrait-anim-4"];
const PORTRAIT_ANIM_COUNT = PORTRAIT_ANIM_CLASSES.length;
function clearPortraitAnimClasses(spot) {
  spot?.classList.remove(...PORTRAIT_ANIM_CLASSES);
}
function assignPortraitAnimClass(spot) {
  clearPortraitAnimClasses(spot);
  spot.classList.add(`portrait-anim-${1 + Math.floor(Math.random() * PORTRAIT_ANIM_COUNT)}`);
}
const LOWRES_FACTOR = 0.7;
window.applySpotlightArtFit = function (img) {
  if (!img?.naturalWidth) return;
  const ratio = img.naturalWidth / img.naturalHeight;
  const crop = spotlightCropForAspect(ratio);
  img.style.objectPosition = crop.pos;
  const spot = img.closest(".dash-spotlight");
  if (!spot) return;
  const bg = spot.querySelector(".dash-spotlight-art-bg");
  const sheen = spot.querySelector(".dash-spotlight-sheen");
  const src = img.currentSrc || img.src;

  if (crop.portrait && bg) {
    img.style.objectFit = crop.fit;
    if (src && bg.src !== src) bg.src = src;
    spot.classList.add("has-portrait-art");
    spot.classList.remove("is-lowres-art");
    assignPortraitAnimClass(spot);
    bg.classList.add("is-loaded");
    if (sheen) {
      const w = Math.min(spot.clientWidth, spot.clientHeight * ratio);
      sheen.style.width = `${w}px`;
    }
  } else {
    spot.classList.remove("has-portrait-art");
    clearPortraitAnimClasses(spot);
    if (sheen) sheen.style.width = "";

    const slotW = (spot.clientWidth || 0) * (window.devicePixelRatio || 1);
    const lowRes = img.naturalWidth > 0 && slotW > 0
      && img.naturalWidth < slotW * LOWRES_FACTOR;

    if (lowRes && bg) {
      img.style.objectFit = "contain";
      // Contained low-res art is pillarboxed; pin its right edge to the
      // container's right edge (inline wins over the stylesheet rule).
      img.style.objectPosition = "100% 40%";
      if (src && bg.src !== src) bg.src = src;
      spot.classList.add("is-lowres-art");
      bg.classList.add("is-loaded");
    } else {
      img.style.objectFit = crop.fit;
      spot.classList.remove("is-lowres-art");
      bg?.classList.remove("is-loaded");
    }
  }
  spot._spotlightSyncHover?.();
};
window.spotlightArtFallback = function (img) {
  const list = (img.dataset.spotlightCandidates || "").split("|").filter(Boolean);
  let idx = parseInt(img.dataset.spotlightIdx || "0", 10) + 1;
  const spot = img.closest(".dash-spotlight");
  spot?.classList.remove("has-portrait-art", "is-lowres-art");
  clearPortraitAnimClasses(spot);
  while (idx < list.length) {
    if (img.src !== list[idx]) {
      img.dataset.spotlightIdx = String(idx);
      img.src = list[idx];
      return;
    }
    idx++;
  }
  const name = img.dataset.name || spot?.querySelector(".dash-spotlight-title")?.textContent?.trim() || "Game";
  const words = name.split(/\s+/).filter(Boolean);
  const initials = (words.slice(0, 3).map(w => w[0]).join("") || "?").toUpperCase().slice(0, 3);
  const safeName = name.replace(/"/g, "&quot;");
  spot?.classList.add("has-art-placeholder");
  spot?.querySelector(".dash-spotlight-art-bg")?.classList.remove("is-loaded");
  if (spot?.querySelector(".dash-spotlight-sheen")) spot.querySelector(".dash-spotlight-sheen").style.width = "";
  img.outerHTML =
    `<div class="dash-spotlight-art dash-spotlight-art-placeholder is-loaded" aria-hidden="true" title="${safeName}">` +
    `<span class="placeholder-initials">${initials}</span></div>`;
  spot?._spotlightSyncHover?.();
};
window.markLandscape = function (img) {
  if (!img?.classList) return;
  const isLandscape = !!(img.naturalWidth && img.naturalHeight && img.naturalWidth > img.naturalHeight * 1.1);
  img.classList.toggle("landscape", isLandscape);
  const src = img.currentSrc || img.src;
  const wrap = img.closest(".cover-wrap");
  if (wrap) {
    wrap.classList.toggle("landscape", isLandscape);
    // Letterboxed (contained) covers paint a blurred copy of the art behind
    // them instead of a flat fill. Cleared when the cover fills the frame.
    if (isLandscape && src) wrap.style.setProperty("--cover-blur-img", `url("${src}")`);
    else wrap.style.removeProperty("--cover-blur-img");
  }
  if (src) {
    const had = window.__landscapeCovers.has(src);
    if (isLandscape && !had) { window.__landscapeCovers.add(src); persistLandscapeCache(); }
    else if (!isLandscape && had) { window.__landscapeCovers.delete(src); persistLandscapeCache(); }
  }
};

const PORTRAIT_COVER_IMG_SELECTOR =
  "img.cover, img.pick-cover, img.deal-hero-cover, img.claim-row-cover, img.claim-cover-thumb";

/**
 * Portrait cover slot HTML — wrap + img with landscape letterbox hooks.
 * `url` must already be escapeAttr'd. Returns empty string when no url.
 */
export function portraitCoverImgHtml(url, imgClass, wrapExtraClass = "") {
  const cover = String(url || "").trim();
  if (!cover) return "";
  const ls = window.coverLandscapeAttr(cover);
  const wrapCls = `cover-wrap${wrapExtraClass ? ` ${wrapExtraClass}` : ""}${ls}`;
  const imgCls = `${imgClass}${ls}`;
  return `<span class="${wrapCls}"><img class="${imgCls}" src="${cover}" alt="" loading="lazy" onload="window.markLandscape(this)" /></span>`;
}

/** Virtual scroll rebuilds rows from HTML; cached images often skip inline onload. */
export function syncCoverFits(root) {
  if (!root?.querySelectorAll) return;
  for (const img of root.querySelectorAll(PORTRAIT_COVER_IMG_SELECTOR)) {
    if (img.complete && img.naturalWidth > 0) window.markLandscape(img);
    else img.addEventListener("load", () => window.markLandscape(img), { once: true });
  }
}

/** Exposed for tests — selector used by syncCoverFits. */
export const portraitCoverImgSelector = PORTRAIT_COVER_IMG_SELECTOR;
