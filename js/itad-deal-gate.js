/**
 * Hide wishlist/dashboard deal surfaces until ITAD is connected (validated API key).
 */
import { isItadDealsAvailable } from './connections-status.js';
import { state } from './state.js';
import { savePrefs } from './prefs.js';
import { applyColumnVisibility } from './table-columns.js';

export { isItadDealsAvailable };

let _lastItadAvailable = null;

/** Reset connect-edge tracking (Vitest). */
export function _resetItadDealGateForTests() {
  _lastItadAvailable = null;
}

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
  if (state.prefs.dealStealsOnly) {
    state.prefs.dealStealsOnly = false;
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
 * Reloads itad_prices.json when ITAD becomes connected (or meta is still null)
 * so a boot race that wiped libraryMeta.itad before auth arrived can heal.
 * @param {{ rerender?: boolean }} [options]
 */
export async function syncItadDealSurfaces(options = {}) {
  const available = isItadDealsAvailable();
  const prev = _lastItadAvailable;
  _lastItadAvailable = available;

  if (typeof document !== 'undefined') {
    document.documentElement.dataset.itadDeals = available ? '1' : '0';
    document.getElementById('dashboardWishlistStats')?.classList.toggle('hidden', !available);
    // Wishlist Deals is a wishlist-only pick tab. Never unhide it on library/itch
    // (updateViewChrome awaits this after updatePickTabsVisibility).
    const showWishlistDeals = available && state.activeView === 'wishlist';
    document.querySelector('[data-tab="wishlistDeals"]')?.classList.toggle('hidden', !showWishlistDeals);
    document.getElementById('wishlistItadCta')?.classList.toggle('hidden', available);
  }

  if (!available && prev !== false) {
    clearItadDealPrefs();
  }

  applyColumnVisibility(state.activeView);

  // Boot races reloadGames (loadItadPrices) with initConnections. If library
  // load wins while ITAD is still disconnected, meta is wiped; auth-status
  // must reload prices (stubItadConnected already did this explicitly).
  const needsPriceReload = available && (prev !== true || !state.libraryMeta?.itad);
  const priceReload = needsPriceReload
    ? import('./library-load.js')
      .then((m) => m.loadItadPrices())
      .then(() => {
        if (typeof document === 'undefined') return;
        return import('./fetcher/render/dashboard.js')
          .then((m) => {
            try { m.renderDashboardFetcherHealth?.(); } catch (_) { /* not mounted */ }
          })
          .catch(() => {});
      })
      .catch(() => {})
    : Promise.resolve();

  if (options.rerender === false) {
    await priceReload;
    return;
  }

  if (typeof document === 'undefined') {
    await priceReload;
    return;
  }

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

  await priceReload;
}
