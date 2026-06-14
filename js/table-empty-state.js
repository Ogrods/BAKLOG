/**
 * Zero-row table empty state HTML — kept out of filters-ui.js so table-ui.js
 * can import it without a circular dependency (filters-ui imports table-ui).
 */

import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import { collectActiveFilters } from './active-filters.js';
import { visibleItchGames } from './connections-status.js';

function shouldShowConnectionsCta(view) {
  if (view === 'library') return state.allGames.length === 0;
  if (view === 'wishlist') return state.wishlistGames.length === 0;
  if (view === 'itch') return visibleItchGames().length === 0;
  return false;
}

/** Full-width tbody row when filter/sort yields zero visible games. */
export function buildTableEmptyStateHtml(view, colspan = 13) {
  const col = Math.max(1, colspan);
  const pills = collectActiveFilters();
  const catalogEmpty = view === 'library' && state.allGames.length === 0;
  const hasFilters = !catalogEmpty && pills.length > 0;

  if (hasFilters) {
    const actions = [
      `<button type="button" class="table-empty-state-btn" data-table-clear-filters title="Clear all active filters">Clear all filters</button>`,
    ];
    if (view === "itch" && state.sessionPrefs.itchHideNonGames) {
      actions.push(
        `<button type="button" class="table-empty-state-btn table-empty-state-btn-secondary" data-table-show-itch-nongames title="Include tools, soundtracks, and other non-game itch.io items">Show non-games</button>`,
      );
    }
    return `<tr class="table-empty-state-row"><td colspan="${col}"><div class="table-empty-state" role="status">
      <p class="table-empty-state-title">No games match your filters</p>
      <p class="table-empty-state-hint">Try clearing a filter or loosening your search.</p>
      <div class="table-empty-state-actions">${actions.join("")}</div>
    </div></td></tr>`;
  }

  let title = "Nothing to show";
  let hint = "";
  if (view === "library") {
    title = state.allGames.length ? "No games in this view" : "Your library is empty";
    hint = state.allGames.length
      ? "Check Hidden games (⋮ menu) or connect another store."
      : "Open Connections, connect a store, then run a fetch from Fetcher health.";
  } else if (view === "wishlist") {
    title = state.wishlistGames.length ? "No wishlist items match" : "Your wishlist is empty";
    hint = state.wishlistGames.length
      ? "Adjust filters or check which stores are connected."
      : "Connect a store on Connections and run its wishlist fetcher.";
  } else if (view === "itch") {
    const itchCount = visibleItchGames().length;
    title = itchCount ? "No itch items in this view" : "No itch.io library loaded";
    hint = itchCount
      ? "Turn on “Show non-games” in the filter bar if you expect zines or tools."
      : "Add your itch.io API key on Connections and run the itch fetcher.";
  }

  const actions = shouldShowConnectionsCta(view)
    ? `<div class="table-empty-state-actions"><button type="button" class="table-empty-state-btn" data-table-goto-connections title="Connect stores and sync your library">Open Connections</button></div>`
    : '';

  return `<tr class="table-empty-state-row"><td colspan="${col}"><div class="table-empty-state" role="status">
    <p class="table-empty-state-title">${escapeHtml(title)}</p>
    <p class="table-empty-state-hint">${escapeHtml(hint)}</p>
    ${actions}
  </div></td></tr>`;
}
