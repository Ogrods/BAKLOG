/**
 * Hide wishlist/dashboard deal surfaces until ITAD is connected (validated API key).
 */
import { isItadDealsAvailable } from './connections-status.js';
import { state } from './state.js';
import { savePrefs } from './prefs.js';
import { applyColumnVisibility } from './table-columns.js';

export { isItadDealsAvailable };

let _lastItadAvailable = null;

/** Clear deal filters/sort prefs that only apply when ITAD pricing is active. */
export function clearItadDealPrefs() {
  let changed = false;
  if (state.prefs.dealOnSaleOnly) {
    state.prefs.dealOnSaleOnly = false;
    changed = true;
  }
  if (state.prefs.dealHistoricalLowOnly) {
    state.prefs.dealHistoricalLowOnly = false;
    changed = true;
  }
  if (state.prefs.dealHideOwned) {
    state.prefs.dealHideOwned = false;
    changed = true;
  }
  if (+state.prefs.dealMinDiscount > 0) {
    state.prefs.dealMinDiscount = 0;
    changed = true;
  }
  if (+state.prefs.dealMaxPrice < 100) {
    state.prefs.dealMaxPrice = 100;
    changed = true;
  }
  const wishlistSort = state.prefs.sort?.wishlist;
  if (wishlistSort?.key === 'deal_price') {
    state.prefs.sort.wishlist = { key: 'steam', dir: -1 };
    changed = true;
  }
  if (changed) savePrefs();
  return changed;
}

/** True when the price column should render on the wishlist table. */
export function isWishlistPriceColumnAvailable() {
  return isItadDealsAvailable();
}

/**
 * Reconcile DOM + prefs when ITAD connect state changes.
 * @param {{ rerender?: boolean }} [options]
 */
export function syncItadDealSurfaces(options = {}) {
  const available = isItadDealsAvailable();
  const prev = _lastItadAvailable;
  _lastItadAvailable = available;

  if (typeof document !== 'undefined') {
    document.documentElement.dataset.itadDeals = available ? '1' : '0';
    document.getElementById('dashboardWishlistStats')?.classList.toggle('hidden', !available);
    document.querySelector('[data-tab="wishlistDeals"]')?.classList.toggle('hidden', !available);
    document.getElementById('wishlistItadCta')?.classList.toggle('hidden', available);
  }

  if (!available && prev !== false) {
    clearItadDealPrefs();
  }

  applyColumnVisibility(state.activeView);

  if (options.rerender === false) return;

  if (typeof document === 'undefined') return;

  if (state.activeView === 'wishlist') {
    void import('./filters-ui.js').then((m) => {
      m.renderSummary();
      m.updateWishlistDrawerVisibility();
      m.updatePickTabsVisibility();
    });
    void import('./picks-ui.js').then((m) => m.renderPicks());
    void import('./table-ui.js').then((m) => m.renderTable?.());
  } else if (state.activeView === 'dashboard') {
    void import('./dashboard.js').then((m) => m.scheduleDashboardRender?.());
  }
}
