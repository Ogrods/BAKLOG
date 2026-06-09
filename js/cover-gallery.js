import { state } from './state.js';
import {
  gameKey,
  coverArtCandidates,
  landscapeArtCandidates,
  storeBadgeHtml,
  wishlistBadgeHtml,
} from './game-core.js';
import { trapFocus } from './focus-trap.js';
import { visibleListForKeyboard } from './table-ui.js';

/** @type {HTMLDialogElement | null} */
let dialog = null;
/** @type {(() => void) | null} */
let releaseTrap = null;
/** @type {object[]} */
let galleryList = [];
let galleryIndex = 0;
/** @type {string[]} */
let artCandidates = [];
let artCandidateIndex = 0;

const GALLERY_MODE_KEY = 'baklog.coverGalleryMode';

const MAX_VIEW_W = 1100;
const MAX_VIEW_H_RATIO = 0.85;

/** @type {'cover' | 'landscape'} */
function loadGalleryMode() {
  try {
    const v = localStorage.getItem(GALLERY_MODE_KEY);
    return v === 'landscape' ? 'landscape' : 'cover';
  } catch {
    return 'cover';
  }
}

/** @type {'cover' | 'landscape'} */
let galleryMode = loadGalleryMode();

function persistGalleryMode() {
  try {
    localStorage.setItem(GALLERY_MODE_KEY, galleryMode);
  } catch { /* ignore quota / private mode */ }
}

const ORIENT_ICON_COVER = `<svg viewBox="0 0 20 20" aria-hidden="true" class="cover-gallery-orient-icon"><rect x="6" y="3" width="8" height="14" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
const ORIENT_ICON_LANDSCAPE = `<svg viewBox="0 0 20 20" aria-hidden="true" class="cover-gallery-orient-icon"><rect x="2" y="6" width="16" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;

const ICON_CLOSE = `<svg viewBox="0 0 24 24" aria-hidden="true" class="cover-gallery-btn-icon"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
const ICON_CHEVRON_PREV = `<svg viewBox="0 0 24 24" aria-hidden="true" class="cover-gallery-btn-icon"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_CHEVRON_NEXT = `<svg viewBox="0 0 24 24" aria-hidden="true" class="cover-gallery-btn-icon"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function syncOrientToggle(btn) {
  if (!(btn instanceof HTMLButtonElement)) return;
  const landscape = galleryMode === 'landscape';
  btn.setAttribute('aria-pressed', landscape ? 'true' : 'false');
  btn.title = landscape ? 'Show cover art' : 'Show landscape art';
  btn.setAttribute('aria-label', btn.title);
  const icon = landscape ? ORIENT_ICON_COVER : ORIENT_ICON_LANDSCAPE;
  const label = landscape ? 'Portrait' : 'Landscape';
  btn.innerHTML = `${icon}<span class="cover-gallery-orient-label">${label}</span>`;
}

function artCandidatesForMode(game) {
  return galleryMode === 'landscape'
    ? landscapeArtCandidates(game)
    : coverArtCandidates(game);
}

/** Portrait and landscape chains can share fallbacks — hide orient when only one unique URL. */
function hasOrientChoice(game) {
  const urls = new Set([...coverArtCandidates(game), ...landscapeArtCandidates(game)]);
  return urls.size > 1;
}

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.className = 'cover-gallery-dialog';
  dialog.setAttribute('aria-label', 'Cover gallery');
  dialog.innerHTML = `
    <div class="cover-gallery-shell">
      <button type="button" class="cover-gallery-close" aria-label="Close cover gallery" title="Close">${ICON_CLOSE}</button>
      <button type="button" class="cover-gallery-nav-btn cover-gallery-nav-prev" data-gallery-nav="prev" aria-label="Previous cover" title="Previous">${ICON_CHEVRON_PREV}</button>
      <div class="cover-gallery-stage">
        <div class="cover-gallery-frame">
          <img class="cover-gallery-img" alt="" decoding="async" />
        </div>
        <div class="cover-gallery-caption">
          <span class="cover-gallery-badge"></span>
          <span class="cover-gallery-name"></span>
          <button type="button" class="cover-gallery-orient-toggle" aria-pressed="false" aria-label="Show landscape art" title="Show landscape art">${ORIENT_ICON_LANDSCAPE}<span class="cover-gallery-orient-label">Landscape</span></button>
        </div>
      </div>
      <button type="button" class="cover-gallery-nav-btn cover-gallery-nav-next" data-gallery-nav="next" aria-label="Next cover" title="Next">${ICON_CHEVRON_NEXT}</button>
    </div>`;

  const closeBtn = dialog.querySelector('.cover-gallery-close');
  const orientBtn = dialog.querySelector('.cover-gallery-orient-toggle');
  const prevBtn = dialog.querySelector('[data-gallery-nav="prev"]');
  const nextBtn = dialog.querySelector('[data-gallery-nav="next"]');
  const img = dialog.querySelector('.cover-gallery-img');

  closeBtn?.addEventListener('click', () => closeCoverGallery());
  orientBtn?.addEventListener('click', (e) => {
    // Stop the backdrop close handler: syncOrientToggle replaces this button's
    // innerHTML, detaching e.target so its closest() lookup would miss.
    e.stopPropagation();
    galleryMode = galleryMode === 'landscape' ? 'cover' : 'landscape';
    persistGalleryMode();
    syncOrientToggle(orientBtn);
    renderSlide(galleryIndex);
  });
  prevBtn?.addEventListener('click', () => galleryPrev());
  nextBtn?.addEventListener('click', () => galleryNext());

  dialog.addEventListener('click', (e) => {
    if (e.target.closest('.cover-gallery-img, .cover-gallery-nav-btn, .cover-gallery-close, .cover-gallery-orient-toggle')) return;
    closeCoverGallery();
  });

  dialog.addEventListener('close', () => cleanupGallery());

  dialog.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      galleryPrev();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      galleryNext();
    }
  });

  img?.addEventListener('load', () => {
    if (img instanceof HTMLImageElement) clampGalleryImage(img);
  });

  img?.addEventListener('error', () => {
    if (!(img instanceof HTMLImageElement)) return;
    artCandidateIndex += 1;
    if (artCandidateIndex < artCandidates.length) {
      img.src = artCandidates[artCandidateIndex];
      return;
    }
    img.alt = 'Cover unavailable';
    img.removeAttribute('src');
  });

  syncOrientToggle(orientBtn);
  document.body.appendChild(dialog);
  return dialog;
}

function viewportCaps() {
  return {
    maxW: Math.min(window.innerWidth * 0.9, MAX_VIEW_W),
    maxH: window.innerHeight * MAX_VIEW_H_RATIO,
  };
}

/** Prevent upscaling beyond natural dimensions while staying within the fixed frame. */
export function clampGalleryImage(img) {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (!nw || !nh) return;
  const frame = img.closest('.cover-gallery-frame');
  let maxW;
  let maxH;
  if (frame && frame.clientWidth && frame.clientHeight) {
    maxW = frame.clientWidth;
    maxH = frame.clientHeight;
  } else {
    ({ maxW, maxH } = viewportCaps());
  }
  img.style.maxWidth = `${Math.min(maxW, nw)}px`;
  img.style.maxHeight = `${Math.min(maxH, nh)}px`;
}

function resetImageSizing(img) {
  img.style.maxWidth = '';
  img.style.maxHeight = '';
}

function galleryBadgeHtml(g) {
  return state.activeView === 'wishlist' ? wishlistBadgeHtml(g) : storeBadgeHtml(g);
}

function renderSlide(index) {
  const dlg = ensureDialog();
  const game = galleryList[index];
  if (!game) return;

  galleryIndex = index;
  const img = dlg.querySelector('.cover-gallery-img');
  const badgeEl = dlg.querySelector('.cover-gallery-badge');
  const nameEl = dlg.querySelector('.cover-gallery-name');
  const prevBtn = dlg.querySelector('[data-gallery-nav="prev"]');
  const nextBtn = dlg.querySelector('[data-gallery-nav="next"]');
  const orientBtn = dlg.querySelector('.cover-gallery-orient-toggle');

  if (!(img instanceof HTMLImageElement)) return;

  artCandidates = artCandidatesForMode(game);
  artCandidateIndex = 0;
  resetImageSizing(img);
  img.alt = game.name || 'Game cover';

  if (artCandidates.length) {
    img.src = artCandidates[0];
    if (img.complete && img.naturalWidth) clampGalleryImage(img);
  } else {
    img.removeAttribute('src');
    img.alt = 'Cover unavailable';
  }

  if (badgeEl) badgeEl.innerHTML = galleryBadgeHtml(game);
  if (nameEl) nameEl.textContent = game.name || '';

  const multi = galleryList.length > 1;
  if (prevBtn instanceof HTMLButtonElement) prevBtn.disabled = !multi;
  if (nextBtn instanceof HTMLButtonElement) nextBtn.disabled = !multi;

  if (orientBtn instanceof HTMLButtonElement) {
    const showOrient = hasOrientChoice(game);
    orientBtn.hidden = !showOrient;
    if (showOrient) syncOrientToggle(orientBtn);
  }

  dlg.setAttribute('aria-label', `${game.name || 'Game'} cover gallery`);
}

function galleryPrev() {
  if (galleryList.length < 2) return;
  const next = (galleryIndex - 1 + galleryList.length) % galleryList.length;
  renderSlide(next);
}

function galleryNext() {
  if (galleryList.length < 2) return;
  const next = (galleryIndex + 1) % galleryList.length;
  renderSlide(next);
}

function cleanupGallery() {
  releaseTrap?.();
  releaseTrap = null;
  galleryList = [];
  galleryIndex = 0;
  artCandidates = [];
  artCandidateIndex = 0;
}

export function closeCoverGallery() {
  if (dialog?.open) dialog.close();
}

/**
 * Open the cover gallery for a table row, cycling the current filtered + sorted list.
 * @param {string} key
 */
export function openCoverGallery(key) {
  const list = state._visibleList || visibleListForKeyboard();
  const index = list.findIndex((g) => gameKey(g) === key);
  if (index < 0) return;

  galleryList = list.slice();
  const dlg = ensureDialog();
  renderSlide(index);

  if (!dlg.open) {
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
    releaseTrap = trapFocus(dlg);
    dlg.focus();
  }
}
