// Window-level cover helpers. Inline `onload`/`onerror` handlers in row HTML
// reach these via `window.coverFallback` / `window.markLandscape`, so this
// module installs them on import (side effect) and also exports
// `syncCoverFits` for callers that need to re-prime cached images.

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
  const fb = img.dataset.fallback;
  if (fb && img.src !== fb) {
    img.src = fb;
    img.dataset.fallback = "";
    return;
  }
  const dashRow = img.closest(".dash-versus-row, .dash-list-row, .coop-pick-row, .dash-spotlight, .itch-hero-card");
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
window.markLandscape = function (img) {
  if (!img?.classList) return;
  const isLandscape = !!(img.naturalWidth && img.naturalHeight && img.naturalWidth > img.naturalHeight * 1.1);
  img.classList.toggle("landscape", isLandscape);
  const wrap = img.closest(".cover-wrap");
  if (wrap) wrap.classList.toggle("landscape", isLandscape);
  const src = img.currentSrc || img.src;
  if (src) {
    const had = window.__landscapeCovers.has(src);
    if (isLandscape && !had) { window.__landscapeCovers.add(src); persistLandscapeCache(); }
    else if (!isLandscape && had) { window.__landscapeCovers.delete(src); persistLandscapeCache(); }
  }
};

/** Virtual scroll rebuilds rows from HTML; cached images often skip inline onload. */
export function syncCoverFits(root) {
  if (!root?.querySelectorAll) return;
  for (const img of root.querySelectorAll("img.cover, img.pick-cover, img.deal-hero-cover")) {
    if (img.complete && img.naturalWidth > 0) window.markLandscape(img);
    else img.addEventListener("load", () => window.markLandscape(img), { once: true });
  }
}
