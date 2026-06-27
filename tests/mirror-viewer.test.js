/* @vitest-environment node */
import { describe, expect, it } from 'vitest';

import {
  catalogArtifactPaths,
  filterMirrorRows,
  mergeMirrorLibrary,
  playtimeHoursFromGame,
  sortMirrorRows,
  summarizeMirrorRows,
} from '../landing/mirror-merge.js';
import { steamCatalogPayload } from './fixtures/synthetic-games.js';

describe('mirror-merge', () => {
  it('picks library catalog artifacts and ignores wishlists', () => {
    const paths = catalogArtifactPaths([
      { path: 'games_steam.json' },
      { path: 'games_wishlist_steam.json' },
      { path: 'games_gog.json' },
      { path: 'data/personal.json' },
    ]);
    expect(paths).toEqual(['games_steam.json', 'games_gog.json']);
  });

  it('merges catalog rows with personal status and playtime', () => {
    const steamDoc = steamCatalogPayload(2);
    steamDoc.games[0].playtime_forever = 120;
    const personal = {
      personal: {
        [`steam:${steamDoc.games[0].id}`]: { status: 'playing', notes: 'Co-op soon' },
      },
    };
    const rows = mergeMirrorLibrary([{ path: 'games_steam.json', doc: steamDoc }], personal);
    expect(rows).toHaveLength(2);
    expect(rows[0].status).toBe('playing');
    expect(rows[0].notes).toBe('Co-op soon');
    expect(rows[0].playtimeHours).toBe(2);
  });

  it('filters by search and status', () => {
    const rows = [
      { key: 'steam:1', store: 'steam', storeLabel: 'Steam', title: 'Alpha', status: 'backlog', statusLabel: 'Backlog', playtimeHours: null, hltbMain: null, notes: '', hidden: false },
      { key: 'steam:2', store: 'steam', storeLabel: 'Steam', title: 'Beta', status: 'playing', statusLabel: 'Playing', playtimeHours: 5, hltbMain: 10, notes: 'notes here', hidden: false },
    ];
    expect(filterMirrorRows(rows, { search: 'notes' })).toHaveLength(1);
    expect(filterMirrorRows(rows, { status: 'playing' })).toHaveLength(1);
    expect(filterMirrorRows(rows, { store: 'gog' })).toHaveLength(0);
  });

  it('sorts by playtime descending', () => {
    const rows = [
      { key: 'steam:1', store: 'steam', storeLabel: 'Steam', title: 'A', status: 'backlog', statusLabel: 'Backlog', playtimeHours: 1, hltbMain: null, notes: '', hidden: false },
      { key: 'steam:2', store: 'steam', storeLabel: 'Steam', title: 'B', status: 'backlog', statusLabel: 'Backlog', playtimeHours: 9, hltbMain: null, notes: '', hidden: false },
    ];
    const sorted = sortMirrorRows(rows, { column: 'playtime', direction: 'desc' });
    expect(sorted.map((r) => r.title)).toEqual(['B', 'A']);
  });

  it('summarizes stores and statuses', () => {
    const rows = mergeMirrorLibrary(
      [
        { path: 'games_steam.json', doc: steamCatalogPayload(1) },
        { path: 'games_gog.json', doc: { games: [{ store: 'gog', id: 'x', name: 'GOG Game' }] } },
      ],
      { personal: {} },
    );
    const summary = summarizeMirrorRows(rows);
    expect(summary.total).toBe(2);
    expect(summary.stores).toEqual(['steam', 'gog']);
  });

  it('converts steam playtime minutes to hours', () => {
    expect(playtimeHoursFromGame({ playtime_forever: 90 })).toBe(1.5);
  });
});
