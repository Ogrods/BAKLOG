/**
 * Tests for js/table-ui.js::tableFingerprint — cache invalidation inputs.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { loadSessionPrefs } from '../js/prefs.js';
import { syncSponsoredTableAfterDismiss, tableFingerprint } from '../js/table-ui.js';
import {
  dismissSponsoredDeal,
  __resetDismissedSponsorsForTest,
  __setSponsorsForTest,
  sponsoredTableRowHtml,
} from '../js/sponsored-deals.js';

function resetState() {
  state.activeView = 'library';
  state.sortKey = 'name';
  state.sortDir = 1;
  state.sessionPrefs = loadSessionPrefs();
  state.prefs = {
    storeFilter: '',
    wishlistStoreFilter: '',
    releaseYearFilter: '',
    hltbBucket: null,
    genreFilters: [],
    genreFilterMode: 'OR',
    dealOnSaleOnly: false,
    dealHistoricalLowOnly: false,
    dealHideOwned: false,
    dealMinDiscount: 0,
    dealMaxPrice: 100,
    columns: {},
    coopFilterMode: 'off',
  };
  state.cleanupModeActive = false;
  state.allGames = [{ store: 'steam', id: 1, appid: 1, name: 'A' }];
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
}

beforeEach(() => {
  resetState();
});

describe('tableFingerprint', () => {
  it('is stable when tracked inputs are unchanged', () => {
    const a = tableFingerprint();
    const b = tableFingerprint();
    expect(a).toBe(b);
  });

  it('changes when sort, search, store filter, deal prefs, or coop mode change', () => {
    const base = tableFingerprint();
    state.sortKey = 'playtime';
    expect(tableFingerprint()).not.toBe(base);

    resetState();
    const b2 = tableFingerprint();
    state.sessionPrefs.search = 'zelda';
    expect(tableFingerprint()).not.toBe(b2);

    resetState();
    const b3 = tableFingerprint();
    state.prefs.storeFilter = 'steam';
    expect(tableFingerprint()).not.toBe(b3);

    resetState();
    const b4 = tableFingerprint();
    state.prefs.dealMinDiscount = 25;
    expect(tableFingerprint()).not.toBe(b4);

    resetState();
    const b5 = tableFingerprint();
    state.prefs.coopFilterMode = 'online';
    expect(tableFingerprint()).not.toBe(b5);

    resetState();
    const b6 = tableFingerprint();
    state.cleanupModeActive = true;
    expect(tableFingerprint()).not.toBe(b6);
  });

  it('changes when library row counts or data version change', () => {
    const base = tableFingerprint();
    state.allGames.push({ store: 'steam', id: 2, appid: 2, name: 'B' });
    expect(tableFingerprint()).not.toBe(base);

    resetState();
    const b2 = tableFingerprint();
    window._dataVersion = 3;
    expect(tableFingerprint()).not.toBe(b2);
  });
});

describe('syncSponsoredTableAfterDismiss', () => {
  beforeEach(() => {
    __resetDismissedSponsorsForTest();
    __setSponsorsForTest({ version: 2, ads: {}, locations: {} });
  });

  it('removes the sponsored table row when no creative remains', () => {
    document.body.innerHTML = `
      <table><tbody id="tbody">
        <tr data-row-index="0"><td>Game A</td></tr>
        <tr class="sponsored-table-row"><td>Encore ad</td></tr>
        <tr data-row-index="1"><td>Game B</td></tr>
      </tbody></table>`;
    syncSponsoredTableAfterDismiss();
    expect(document.querySelector('.sponsored-table-row')).toBeNull();
    expect(document.querySelectorAll('#tbody tr').length).toBe(2);
  });

  it('swaps in the next eligible creative in place instead of collapsing', () => {
    __setSponsorsForTest({
      version: 2,
      ads: {
        'ad-a': { kind: 'sponsor', title: 'Encore', tagline: 'a', cta: 'Go', url: 'https://x.test/' },
        'ad-b': { kind: 'sponsor', title: 'Ironveil', tagline: 'b', cta: 'Go', url: 'https://x.test/' },
      },
      locations: { 'lib-row': ['ad-a', 'ad-b'] },
    });
    document.body.innerHTML = `
      <table><tbody id="tbody">
        <tr data-row-index="0"><td>Game A</td></tr>
        <tr class="sponsored-table-row" data-sponsor-id="ad-a"><td>Encore ad</td></tr>
        <tr data-row-index="1"><td>Game B</td></tr>
      </tbody></table>`;
    dismissSponsoredDeal('ad-a');
    syncSponsoredTableAfterDismiss();
    const row = document.querySelector('.sponsored-table-row');
    expect(row).not.toBeNull();
    expect(document.querySelectorAll('#tbody tr').length).toBe(3);
    expect(row.textContent).toContain('Ironveil');
    expect(row.classList.contains('sponsored-table-row--house')).toBe(false);
  });

  it('swaps sponsor row for house promo in sponsor shell (same row height layout)', () => {
    __setSponsorsForTest({
      version: 2,
      ads: {
        'ad-a': { kind: 'sponsor', title: 'Encore', tagline: 'a', cta: 'Go', url: 'https://x.test/' },
        'house-pro': {
          kind: 'house',
          title: 'BAKLOG Pro',
          tagline: 'Bulk-refresh every store.',
          cta: 'Get Pro',
          url: 'https://buy.polar.sh/test',
        },
      },
      locations: { 'lib-row': ['ad-a', 'house-pro'] },
    });
    const sponsorRow = sponsoredTableRowHtml(
      { kind: 'sponsor', id: 'ad-a', title: 'Encore', tagline: 'a', cta: 'Go', url: 'https://x.test/' },
      { locationKey: 'lib-row', tableLayout: 'sponsor' },
    );
    document.body.innerHTML = `
      <table><tbody id="tbody">
        <tr data-row-index="0"><td>Game A</td></tr>
        ${sponsorRow}
        <tr data-row-index="1"><td>Game B</td></tr>
      </tbody></table>`;
    dismissSponsoredDeal('ad-a');
    syncSponsoredTableAfterDismiss();
    const row = document.querySelector('.sponsored-table-row');
    expect(row).not.toBeNull();
    expect(row.textContent).toContain('BAKLOG Pro');
    expect(row.classList.contains('sponsored-table-row--house')).toBe(false);
    expect(row.querySelector('.house-table-kicker')).toBeNull();
    expect(row.querySelector('.sponsored-table-badge')).not.toBeNull();
  });
});
