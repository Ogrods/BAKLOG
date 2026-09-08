import { describe, expect, it } from 'vitest';
import {
  catalogArtifactPaths,
  filterMirrorRows,
  formatItadPriceLabel,
  mergeItadPrices,
  mergeMirrorLibrary,
  mirrorCoverUrlFor,
  sortMirrorRows,
  summarizeMirrorRows,
} from '../landing/mirror-merge.js';

describe('mirror-merge', () => {
  it('merges library catalogs with personal overlays', () => {
    const rows = mergeMirrorLibrary(
      [
        {
          path: 'games_steam.json',
          doc: {
            games: [
              { id: '1', name: 'Alpha', status: 'backlog', store: 'steam' },
              { id: '2', name: 'Beta', status: 'finished', store: 'steam' },
            ],
          },
        },
      ],
      {
        personal: {
          'steam:1': { status: 'playing', notes: 'fun' },
        },
      },
    );
    expect(rows.length).toBe(2);
    const alpha = rows.find((r) => r.title === 'Alpha');
    expect(alpha?.status).toBe('playing');
    expect(alpha?.notes).toBe('fun');
  });

  it('passes cover URL and catalog metrics through', () => {
    const rows = mergeMirrorLibrary(
      [
        {
          path: 'games_steam.json',
          doc: {
            games: [
              {
                id: '730',
                name: 'CS',
                store: 'steam',
                library_image: 'https://cdn.example/lib.jpg',
                steam_percent: 88,
                metacritic: 81,
                hltb_main_hours: 10,
                hltb_extra_hours: 20,
                genres: ['Action', 'FPS', 'Extra'],
                release_date: '2012-08-21',
                rtime_last_played: 1700000000,
              },
            ],
          },
        },
      ],
      {},
    );
    expect(rows[0].coverUrl).toBe('https://cdn.example/lib.jpg');
    expect(rows[0].steamPercent).toBe(88);
    expect(rows[0].metacritic).toBe(81);
    expect(rows[0].hltbMain).toBe(10);
    expect(rows[0].hltbExtra).toBe(20);
    expect(rows[0].genres).toEqual(['Action', 'FPS']);
    expect(rows[0].released).toMatch(/2012/);
    expect(rows[0].lastPlayed).toBeTruthy();
  });

  it('falls back to Steam header CDN for cover', () => {
    expect(mirrorCoverUrlFor({ store: 'steam', id: '570' })).toBe(
      'https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg',
    );
    expect(mirrorCoverUrlFor({ store: 'gog', id: 'x', library_image: 'ftp://bad' })).toBe('');
  });

  it('joins ITAD prices by game key', () => {
    const rows = mergeMirrorLibrary(
      [{ path: 'games_steam.json', doc: { games: [{ id: '1', name: 'A', store: 'steam' }] } }],
      {},
    );
    const priced = mergeItadPrices(rows, {
      by_key: {
        'steam:1': { price_str: '$4.99', cut: 50, currency: 'USD', price: 4.99 },
      },
    });
    expect(priced[0].priceLabel).toBe('$4.99 (-50%)');
    expect(formatItadPriceLabel({ price: 10, currency: 'USD' })).toBe('USD 10');
  });

  it('filters and sorts', () => {
    const rows = [
      {
        title: 'Zed',
        store: 'steam',
        storeLabel: 'Steam',
        status: 'backlog',
        statusLabel: 'Backlog',
        notes: '',
      },
      {
        title: 'Ace',
        store: 'gog',
        storeLabel: 'GOG',
        status: 'finished',
        statusLabel: 'Finished',
        notes: '',
      },
    ];
    const filtered = filterMirrorRows(rows, { search: 'ace', status: '', store: '' });
    expect(filtered.map((r) => r.title)).toEqual(['Ace']);
    expect(sortMirrorRows(rows, { column: 'title' })[0].title).toBe('Ace');
    const summary = summarizeMirrorRows(rows);
    expect(summary.total).toBe(2);
  });

  it('lists catalog artifact paths', () => {
    expect(
      catalogArtifactPaths([{ path: 'games_steam.json' }, { path: 'data/personal.json' }]),
    ).toEqual(['games_steam.json']);
  });
});
