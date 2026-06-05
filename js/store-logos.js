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
  amazon: 'A',
  xbox: 'X',
  battlenet: 'B',
  nintendo: 'N',
  ubisoft: 'U',
  humble: 'H',
  ea: 'EA',
  itch: 'I',
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
  gog: 'assets/store-logos/gog.svg',
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
  return STORE_LOGO_ASSETS[key]?.color || '#64748b';
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
    const letter = storeLetter(key);
    return `<span class="store-logo store-logo--letter store-logo--${size}${extra}${manual}" style="--store-logo-bg:${escapeAttr(storeBrandColor(key))}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">${escapeHtml(letter)}</span>`;
  }
  return `<span class="store-logo store-logo--glyph store-logo--${size}${extra}${manual}" style="--store-logo-bg:${escapeAttr(asset.color || storeBrandColor(key))};--store-logo-glyph:url('${escapeAttr(asset.glyph)}')" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"><span class="store-logo-glyph" aria-hidden="true"></span></span>`;
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
  const letter = storeLetter(key);
  return `<span class="store-badge ${key}${SIZE_CLASS[size] || ''}${extra}${manual}" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}">${escapeHtml(letter)}</span>`;
}

/** Row of full SVG store glyphs for the dashboard hero. */
export function storeLogoStripHtml(stores, { size = 'md', max = 12 } = {}) {
  const keys = sortStoresByDisplayOrder(stores).slice(0, max);
  if (!keys.length) return '';
  return `<div class="store-logo-strip store-logo-strip--${size}" role="list" aria-label="Stores in your library">${keys.map(k => `<span role="listitem">${storeGlyphHtml(k, { size, title: storeDisplayName(k) })}</span>`).join('')}</div>`;
}
