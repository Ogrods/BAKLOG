import { describe, expect, it } from 'vitest';
import {
  claimRowStatus,
  computeOverviewStats,
  coverLookupKey,
  diffPublishFeeds,
  filterClaimsItems,
  groupDuplicates,
  missingPublishFields,
  slugManualId,
  sortClaimsItems,
  stripClaimTitleDecorations,
} from '../admin/claims-workspace.js';

describe('coverLookupKey', () => {
  it('strips giveaway boilerplate', () => {
    expect(coverLookupKey('Rogue Waters (Steam) Giveaway')).toBe('rogue waters');
    expect(coverLookupKey('Songs of Conquest Free on Epic Game Store')).toBe('songs of conquest');
  });
});

describe('stripClaimTitleDecorations', () => {
  it('strips (store) Giveaway suffix', () => {
    expect(stripClaimTitleDecorations('Rogue Waters (Steam) Giveaway')).toBe('Rogue Waters');
  });

  it('strips free on <store>', () => {
    expect(stripClaimTitleDecorations('Madness Inside free on itch.io')).toBe('Madness Inside');
    expect(stripClaimTitleDecorations('Foo on GOG')).toBe('Foo');
  });

  it('strips free at EGS / Epic Game Store', () => {
    expect(stripClaimTitleDecorations('Songs of Conquest Free on Epic Game Store')).toBe('Songs of Conquest');
  });

  it('strips trailing Giveaway', () => {
    expect(stripClaimTitleDecorations('Tell Me Why Giveaway')).toBe('Tell Me Why');
  });

  it('leaves a clean title untouched', () => {
    expect(stripClaimTitleDecorations('Control')).toBe('Control');
  });
});

describe('claimRowStatus', () => {
  const approved = new Set(['epic-1']);
  const now = Date.parse('2026-06-08T12:00:00Z');

  it('flags expired selected auto row', () => {
    const st = claimRowStatus(
      { id: 'epic-1', store: 'epic', title: 'Foo', claim_url: 'https://x', ends_at: '2026-06-01T00:00:00Z' },
      { now, approvedIds: approved, isAuto: true },
    );
    expect(st.expired).toBe(true);
    expect(st.publishState).toBe('expired');
  });

  it('flags missing fields', () => {
    const st = claimRowStatus(
      { id: 'epic-2', store: '', title: 'Bar', claim_url: '' },
      { now, approvedIds: approved, isAuto: true },
    );
    expect(st.missing).toEqual(['store', 'claim_url']);
    expect(st.publishState).toBe('not_selected');
  });

  it('marks will_publish when selected and valid', () => {
    const st = claimRowStatus(
      { id: 'epic-1', store: 'epic', title: 'Foo', claim_url: 'https://x', ends_at: '2026-12-01T00:00:00Z' },
      { now, approvedIds: approved, isAuto: true },
    );
    expect(st.publishState).toBe('will_publish');
    expect(st.publishable).toBe(true);
  });
});

describe('groupDuplicates', () => {
  it('groups same normalized title', () => {
    const items = [
      { id: 'a', title: 'Rogue Waters (Steam) Giveaway', source: 'gamerpower' },
      { id: 'b', title: 'Rogue Waters Free on Steam', source: 'itad' },
      { id: 'c', title: 'Unique Game', source: 'epic' },
    ];
    const groups = groupDuplicates(items);
    expect(groups.size).toBe(1);
    expect(groups.get('rogue waters')).toHaveLength(2);
  });
});

describe('filterClaimsItems', () => {
  const items = [
    { id: '1', store: 'steam', source: 'gamerpower', title: 'Alpha', claim_url: 'https://a' },
    { id: '2', store: 'epic', source: 'epic', title: 'Beta', claim_url: 'https://b' },
  ];
  const approvedIds = new Set(['1']);

  it('filters by store', () => {
    expect(filterClaimsItems(items, { store: 'epic', approvedIds })).toHaveLength(1);
  });

  it('filters by search', () => {
    expect(filterClaimsItems(items, { search: 'alpha', approvedIds })).toHaveLength(1);
  });

  it('filters selected', () => {
    expect(filterClaimsItems(items, { status: 'selected', approvedIds })).toHaveLength(1);
  });
});

describe('sortClaimsItems', () => {
  it('sorts by title', () => {
    const sorted = sortClaimsItems(
      [{ title: 'Zed' }, { title: 'Alpha' }],
      'title',
    );
    expect(sorted[0].title).toBe('Alpha');
  });
});

describe('diffPublishFeeds', () => {
  it('detects added, removed, updated', () => {
    const live = [{ id: 'a', title: 'Old', store: 'steam', claim_url: 'https://a' }];
    const pending = [
      { id: 'a', title: 'New', store: 'steam', claim_url: 'https://a' },
      { id: 'b', title: 'Brand', store: 'epic', claim_url: 'https://b' },
    ];
    const diff = diffPublishFeeds(live, pending);
    expect(diff.added).toHaveLength(1);
    expect(diff.removed).toHaveLength(0);
    expect(diff.updated).toHaveLength(1);
    expect(diff.updated[0].id).toBe('a');
  });
});

describe('slugManualId', () => {
  it('builds store-prefixed slug', () => {
    expect(slugManualId('Control', 'epic')).toBe('epic-control');
  });
});

describe('missingPublishFields', () => {
  it('lists all missing', () => {
    expect(missingPublishFields({})).toEqual(['id', 'store', 'claim_url']);
  });
});

describe('computeOverviewStats', () => {
  it('counts overview buckets', () => {
    const now = Date.parse('2026-06-08T12:00:00Z');
    const items = [
      { id: '1', title: 'A', store: 'steam', claim_url: 'x', ends_at: '2026-06-09T00:00:00Z' },
      { id: '2', title: 'B', store: 'epic', claim_url: 'y', ends_at: '2026-05-01T00:00:00Z' },
      { id: '3', title: 'C', store: 'gog', claim_url: 'z' },
    ];
    const stats = computeOverviewStats(items, new Set(['1', '2']), now);
    expect(stats.total).toBe(3);
    expect(stats.selected).toBe(2);
    expect(stats.expired).toBe(1);
    expect(stats.expiring).toBe(1);
  });
});
