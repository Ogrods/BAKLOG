// Shared storefront badges: letter badges everywhere, full SVG glyphs in the dashboard hero strip.
import { escapeAttr, escapeHtml } from './dom-util.js';
import { DASH_STORE_LABELS, sortStoresByDisplayOrder } from './dashboard-shared.js';
import { STORE_BRAND_COLORS } from './store-brand-colors.js';

/** Canonical single-letter (or short) labels per store key. */
export const STORE_BADGE_LETTERS = {
  steam: 'S',
  gog: 'G',
  psn: 'P',
  epic: 'E',
  epic_mobile: 'Em',
  amazon: 'A',
  xbox: 'X',
  battlenet: 'B',
  nintendo: 'N',
  ubisoft: 'U',
  humble: 'H',
  ea: 'EA',
  itch: 'I',
  indiegala: 'IG',
  itad: 'I',
  other: '?',
  manual: 'M',
  wishlist: 'W',
};

const SIZE_CLASS = {
  sm: '',
  md: ' store-badge--md',
  lg: ' store-badge--lg',
};

/**
 * SVG mask glyphs + brand colors — only used by the dashboard hero strip
 * (storeLogoStripHtml). Everywhere else uses letter badges (storeLogoHtml).
 * @type {Readonly<Record<string, { glyph: string, color: string }>>}
 */
const STORE_GLYPH_PATHS = {
  steam: 'assets/store-logos/steam.svg',
  epic: 'assets/store-logos/epic.svg',
  epic_mobile: 'assets/store-logos/epic.svg',
  humble: 'assets/store-logos/humble-h.svg',
  psn: 'assets/store-logos/playstation.svg',
  xbox: 'assets/store-logos/xbox.svg',
  nintendo: 'assets/store-logos/nintendo.svg',
  amazon: 'assets/store-logos/amazon.svg',
  itch: 'assets/store-logos/itch.svg',
  battlenet: 'assets/store-logos/battlenet.svg',
  ubisoft: 'assets/store-logos/ubisoft.svg',
  ea: 'assets/store-logos/ea.svg',
};

/** @type {Readonly<Record<string, { glyph: string, color: string }>>} */
export const STORE_LOGO_ASSETS = Object.fromEntries(
  Object.entries(STORE_GLYPH_PATHS).map(([key, glyph]) => [
    key,
    { glyph, color: STORE_BRAND_COLORS[key] },
  ]),
);

/**
 * Short lowercase wordmarks rendered (instead of a single letter) inside the
 * dashboard hero badge for letter-fallback stores. Hero strip only.
 */
const HERO_WORDLETS = { gog: 'gog' };

/**
 * Per-store optical centering nudges (in px) for the 18px connections rail
 * badge only. Several brand SVGs carry asymmetric visual weight in their
 * viewBox, so geometric centering reads off — these offsets translate the
 * masked glyph so each icon sits visually centered between the status dot and
 * the label. Applied via `.conn-rail-badge .store-badge-glyph` transform in
 * app.css; stores omitted here (or set to 0) render unshifted.
 * @type {Readonly<Record<string, { x?: number, y?: number }>>}
 */
export const STORE_RAIL_GLYPH_OFFSET = {
  steam: { x: 1.5 },
  epic: { x: 0.5 },
  epic_mobile: { x: 0.5 },
  psn: { x: 0.5 },
  xbox: {},
  nintendo: { x: 0.5 },
  amazon: { x: -0.5, y: -0.5 },
  itch: {},
  humble: {},
  battlenet: { x: 0.5 },
  ubisoft: { x: 0.5 },
  ea: { x: 1 },
};

/** Inline CSS vars for a rail glyph's optical offset, or '' when unshifted. */
function railGlyphOffsetVars(key) {
  const off = STORE_RAIL_GLYPH_OFFSET[key];
  if (!off) return '';
  const x = off.x || 0;
  const y = off.y || 0;
  if (!x && !y) return '';
  let out = '';
  if (x) out += `--store-badge-offset-x:${x}px;`;
  if (y) out += `--store-badge-offset-y:${y}px;`;
  return out;
}

export function storeLetter(store) {
  const key = (store || '').toLowerCase();
  if (STORE_BADGE_LETTERS[key]) return STORE_BADGE_LETTERS[key];
  return (key[0] || '?').toUpperCase();
}

export function storeDisplayName(store) {
  const key = (store || '').toLowerCase();
  return DASH_STORE_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Store';
}

/** Brand color for a store's glyph background (hero strip only). */
export function storeBrandColor(store) {
  const key = (store || '').toLowerCase();
  return STORE_LOGO_ASSETS[key]?.color || STORE_BRAND_COLORS[key] || '#64748b';
}

/**
 * Full SVG glyph badge (CSS mask + brand color) — used only by the dashboard
 * hero strip. Falls back to a letter badge for stores without a glyph asset.
 * @param {string} store
 * @param {{ size?: 'sm'|'md'|'lg', className?: string, title?: string, manual?: boolean }} [opts]
 */
export function storeGlyphHtml(store, opts = {}) {
  const key = (store || '').toLowerCase();
  const asset = STORE_LOGO_ASSETS[key];
  const label = opts.title || storeDisplayName(key);
  const size = opts.size || 'md';
  const extra = opts.className ? ` ${opts.className}` : '';
  const manual = opts.manual ? ' store-logo--manual' : '';
  if (!asset?.glyph) {
    // A few stores read better as a short lowercase wordmark squeezed into the
    // hero badge (e.g. GOG) than as a single letter.
    const word = HERO_WORDLETS[key];
    // Wordmark text is wrapped so its optical-centering nudge doesn't move the
    // square badge box (which must stay aligned with sibling badges).
    const content = word
      ? `<span class="store-logo-word">${escapeHtml(word)}</span>`
      : escapeHtml(storeLetter(key));
    const wordCls = word ? ' store-logo--word' : '';
    return `<span class="store-logo ${key} store-logo--letter${wordCls} store-logo--${size}${extra}${manual}" style="--store-logo-bg:${escapeAttr(storeBrandColor(key))}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">${content}</span>`;
  }
  return `<span class="store-logo ${key} store-logo--glyph store-logo--${size}${extra}${manual}" style="--store-logo-bg:${escapeAttr(asset.color || storeBrandColor(key))};--store-logo-glyph:url('${escapeAttr(asset.glyph)}')" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"><span class="store-logo-glyph" aria-hidden="true"></span></span>`;
}

/**
 * @param {string} store
 * @param {{ size?: 'sm'|'md'|'lg', className?: string, title?: string, manual?: boolean }} [opts]
 */
export function storeLogoHtml(store, opts = {}) {
  const key = (store || '').toLowerCase();
  const label = opts.title || storeDisplayName(key);
  const size = opts.size || 'md';
  const extra = opts.className ? ` ${opts.className}` : '';
  const manual = opts.manual ? ' manual' : '';
  const asset = STORE_LOGO_ASSETS[key];
  // Stores with a brand glyph render the SVG logo (masked, painted with the
  // badge's text color). Abstract keys (other/manual/wishlist/itad) keep the
  // letter fallback, which avoids the optical-centering issues of letterforms.
  if (asset?.glyph) {
    // Optical offsets are tuned for the 18px connections rail badge; only apply
    // them there so dense table/claim/pick badges stay geometrically centered.
    const offsetVars = opts.className?.includes('conn-rail-badge')
      ? railGlyphOffsetVars(key)
      : '';
    return `<span class="store-badge ${key}${SIZE_CLASS[size] || ''} store-badge--glyph${extra}${manual}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"><span class="store-badge-glyph" aria-hidden="true" style="--store-badge-glyph:url('${escapeAttr(asset.glyph)}');${offsetVars}"></span></span>`;
  }
  // GOG reads better as a squeezed lowercase "gog" wordmark than a single "G",
  // so render it sitewide (library, wishlist, picks, claims, connections, etc.).
  const word = HERO_WORDLETS[key];
  if (word) {
    // Inner span carries the upward nudge so the square box stays even with
    // sibling badges (the box itself is not transformed).
    return `<span class="store-badge ${key}${SIZE_CLASS[size] || ''} store-badge--word${extra}${manual}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"><span class="store-badge-word">${escapeHtml(word)}</span></span>`;
  }
  const letter = storeLetter(key);
  return `<span class="store-badge ${key}${SIZE_CLASS[size] || ''}${extra}${manual}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">${escapeHtml(letter)}</span>`;
}

/** Row of full SVG store glyphs for the dashboard hero. */
export function storeLogoStripHtml(stores, { size = 'md', max = 12 } = {}) {
  const keys = sortStoresByDisplayOrder(stores).slice(0, max);
  if (!keys.length) return '';
  return `<div class="store-logo-strip store-logo-strip--${size}" role="list" aria-label="Stores in your library">${keys.map(k => `<span role="listitem">${storeGlyphHtml(k, { size, title: storeDisplayName(k) })}</span>`).join('')}</div>`;
}

/**
 * Column count that keeps wrapped rows balanced.
 * e.g. 12 items with max 11/row → 6 (6+6), not 11+1.
 */
export function balancedWrapColumns(count, maxPerRow) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  const max = Math.max(0, Math.floor(Number(maxPerRow) || 0));
  if (n <= 0) return 0;
  if (max <= 0 || max >= n) return n;
  const rows = Math.ceil(n / max);
  return Math.ceil(n / rows);
}

/** Snap a rendered `.store-logo-strip` to balanced grid columns for its host width. */
export function snapStoreLogoStrip(strip) {
  if (!strip) return;
  const items = strip.querySelectorAll(':scope > [role="listitem"]');
  const n = items.length;
  if (n <= 1) {
    strip.classList.remove('is-balanced-wrap');
    strip.style.removeProperty('--store-strip-cols');
    return;
  }
  const host = strip.parentElement || strip;
  const itemW = items[0].getBoundingClientRect().width;
  if (!(itemW > 0)) {
    strip.classList.remove('is-balanced-wrap');
    strip.style.removeProperty('--store-strip-cols');
    return;
  }
  const styles = getComputedStyle(strip);
  const gap = parseFloat(styles.columnGap || styles.gap) || 0;
  const avail = host.clientWidth || strip.clientWidth;
  if (!(avail > 0)) return;
  const maxPerRow = Math.max(1, Math.floor((avail + gap) / (itemW + gap)));
  const cols = balancedWrapColumns(n, maxPerRow);
  if (cols >= n) {
    strip.classList.remove('is-balanced-wrap');
    strip.style.removeProperty('--store-strip-cols');
    return;
  }
  strip.style.setProperty('--store-strip-cols', String(cols));
  strip.classList.add('is-balanced-wrap');
}

const _heroStoreStripObs = new WeakMap();

/** Observe `.dash-hero-stores` and re-snap the logo strip on resize. */
export function observeHeroStoreStrip(host) {
  if (!host) return;
  const run = () => snapStoreLogoStrip(host.querySelector('.store-logo-strip'));
  if (typeof ResizeObserver === 'function' && !_heroStoreStripObs.has(host)) {
    const ro = new ResizeObserver(() => run());
    _heroStoreStripObs.set(host, ro);
    ro.observe(host);
  }
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(run);
  } else {
    run();
  }
}
