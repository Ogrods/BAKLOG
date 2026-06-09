/**
 * Wishlist/library price cell HTML (extracted from table-ui.js).
 */
import { escapeAttr, escapeHtml } from './dom-util.js';
import {
  cutBucketClass,
  dealDroppedBadgeHtml,
  getDealInfo,
  getItadForGame,
  priceLowStarHtml,
} from './deals.js';
import { formatMoney, currencyMismatchTagForGame, displayCurrency } from './currency.js';

export function formatPrice(g) {
  const itad = getItadForGame(g);
  if (itad?.price != null || itad?.price_str) {
    const onSale = (itad.cut || 0) > 0;
    const cutTxt = onSale ? ` (-${itad.cut}%)` : '';
    const bucket = onSale ? cutBucketClass(itad.cut) : '';
    const itadCur = itad.currency || displayCurrency();
    const priceLabel = itad.price != null
      ? formatMoney(itad.price, itadCur)
      : escapeHtml(itad.price_str);
    const priceInner = onSale
      ? `<span class="price-cut font-semibold ${bucket}">${priceLabel}${escapeHtml(cutTxt)}</span>`
      : priceLabel;
    const d = getDealInfo(g);
    const lowStar = d ? priceLowStarHtml(d) : '';
    const dropBadge = dealDroppedBadgeHtml(g).replace(/^/, '&nbsp;');
    const shopHtml = itad.shop ? `@ ${escapeHtml(itad.shop)}` : '';
    const dealUrl = itad.url || (d && d.url) || null;
    const linkOpen = dealUrl
      ? `<a href="${escapeAttr(dealUrl)}" target="_blank" rel="noopener" class="deal-price-link flex flex-col items-end leading-tight" title="Open this deal on ${escapeAttr(itad.shop || 'store')}">`
      : '<div class="flex flex-col items-end leading-tight">';
    const linkClose = dealUrl ? '</a>' : '</div>';
    return `<div class="deal-price-row flex items-start justify-end gap-1">${lowStar}${linkOpen}
      <span class="whitespace-nowrap">${priceInner}${dropBadge}</span>
      ${shopHtml ? `<span class="text-[10px] text-slate-400 truncate w-full text-right" title="${escapeAttr(itad.shop)}">${shopHtml}</span>` : ''}
    ${linkClose}</div>`;
  }
  if (!g.price && g.discount_percent == null) return ' - ';
  const base = g.price || 'N/A';
  const cut = g.discount_percent || 0;
  const curTag = currencyMismatchTagForGame(g);
  if (cut > 0) {
    const bucket = cutBucketClass(cut);
    return `<span class="price-cut font-semibold ${bucket}">${escapeHtml(base)} (-${cut}%)${curTag}</span>`;
  }
  return `${escapeHtml(base)}${curTag}`;
}
