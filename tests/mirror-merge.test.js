import { describe, expect, it } from 'vitest';
import {
  catalogArtifactPaths,
  filterMirrorRows,
  mergeMirrorLibrary,
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
