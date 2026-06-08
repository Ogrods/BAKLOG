import { describe, expect, it } from 'vitest';
import {
  applyCoverBorrow,
  claimRowStatus,
  computeOverviewStats,
  coverLookupKey,
  coverQuality,
  describePublishDiffUpdate,
  diffPublishFeeds,
  formatPublishDiffValue,
  publishDiffFieldChanges,
  dupeBadgeHtml,
  dupeStampIdSet,
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
    expect(coverLookupKey('Songs of Conquest Free on Epic Game Store')).toBe('songs conquest');
  });

  it('treats & and and as equivalent and drops connector stopwords', () => {
    expect(coverLookupKey('Mr.Brocco & Co')).toBe('mr brocco co');
    expect(coverLookupKey('Mr.Brocco And Co (IndieGala) Giveaway')).toBe('mr brocco co');
    expect(coverLookupKey('Foo + Bar')).toBe('foo bar');
  });
});

describe('applyCoverBorrow', () => {
  const steamPortrait = 'https://cdn.akamai.steamstatic.com/steam/apps/2074560/library_600x900_2x.jpg';
  const gamerpowerBanner = 'https://www.gamerpower.com/offers/1b/68ce9db7d6736.jpg';

  it('upgrades a low-quality cover when a sibling has a better portrait', () => {
    const catalog = [
      {
        id: 'itad-brocco',
        title: 'Mr.Brocco & Co - FREE on IndieGala on IndieGala Store',
        header_image: steamPortrait,
      },
      {
        id: 'gp-brocco',
        title: 'Mr.Brocco And Co (IndieGala) Giveaway',
        header_image: gamerpowerBanner,
      },
    ];
    const items = structuredClone(catalog);
    applyCoverBorrow(items, catalog);
    const gp = items.find((it) => it.id === 'gp-brocco');
    expect(gp.header_image).toBe(steamPortrait);
    expect(coverQuality(gp.header_image)).toBeGreaterThan(coverQuality(gamerpowerBanner));
  });

  it('still fills rows with no cover', () => {
    const catalog = [
      { id: 'a', title: 'Madness Inside (itch.io) Giveaway', header_image: gamerpowerBanner },
    ];
    const items = [{ id: 'b', title: 'Madness Inside free on itch.io', header_image: '' }];
    applyCoverBorrow(items, catalog);
    expect(items[0].header_image).toBe(gamerpowerBanner);
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

  it('groups Mr.Brocco rows when one title uses & and the other uses And', () => {
    const items = [
      { id: 'gp-brocco', title: 'Mr.Brocco And Co (IndieGala) Giveaway', source: 'gamerpower' },
      { id: 'itad-brocco', title: 'Mr.Brocco & Co - FREE on IndieGala on IndieGala Store', source: 'itad' },
    ];
    const groups = groupDuplicates(items);
    expect(groups.size).toBe(1);
    expect(groups.get('mr brocco co')).toHaveLength(2);
  });
});

describe('dupeStampIdSet', () => {
  it('stamps all visible rows when 3 share a normalized title', () => {
    const visibleItems = [
      { id: 'a', title: 'Rogue Waters (Steam) Giveaway' },
      { id: 'b', title: 'Rogue Waters Free on Steam' },
      { id: 'c', title: 'Rogue Waters Giveaway' },
    ];
    const stamped = dupeStampIdSet({ visibleItems, hiddenItems: [] });
    expect([...stamped].sort()).toEqual(['a', 'b', 'c']);
  });

  it('does not stamp lone survivor when siblings are hidden', () => {
    const visibleItems = [{ id: 'keep', title: 'Rogue Waters (Steam) Giveaway' }];
    const hiddenItems = [
      { id: 'hide-a', title: 'Rogue Waters Free on Steam' },
      { id: 'hide-b', title: 'Rogue Waters Giveaway' },
    ];
    const stamped = dupeStampIdSet({ visibleItems, hiddenItems });
    expect(stamped.has('keep')).toBe(false);
    expect(stamped.has('hide-a')).toBe(true);
    expect(stamped.has('hide-b')).toBe(true);
  });

  it('stamps manual and auto rows with the same normalized title', () => {
    const visibleItems = [
      { id: 'auto-1', title: 'Control Free on Epic Game Store' },
      { id: 'manual-control', title: 'Control' },
    ];
    const stamped = dupeStampIdSet({ visibleItems, hiddenItems: [] });
    expect([...stamped].sort()).toEqual(['auto-1', 'manual-control']);
  });

  it('returns empty set for unique titles', () => {
    const visibleItems = [
      { id: 'a', title: 'Alpha' },
      { id: 'b', title: 'Beta' },
    ];
    const stamped = dupeStampIdSet({ visibleItems, hiddenItems: [] });
    expect(stamped.size).toBe(0);
  });

  it('does not stamp a lone hidden copy when all siblings are hidden', () => {
    const hiddenItems = [{ id: 'only-hidden', title: 'Rogue Waters (Steam) Giveaway' }];
    const stamped = dupeStampIdSet({ visibleItems: [], hiddenItems });
    expect(stamped.size).toBe(0);
  });

  it('stamps hidden Mr.Brocco when visible sibling uses & instead of And', () => {
    const visibleItems = [{ id: 'itad-brocco', title: 'Mr.Brocco & Co' }];
    const hiddenItems = [{ id: 'gp-brocco', title: 'Mr.Brocco And Co (IndieGala) Giveaway' }];
    const stamped = dupeStampIdSet({ visibleItems, hiddenItems });
    expect(stamped.has('itad-brocco')).toBe(false);
    expect(stamped.has('gp-brocco')).toBe(true);
  });
});

describe('dupeBadgeHtml', () => {
  it('renders a red dupe stamp badge', () => {
    expect(dupeBadgeHtml()).toContain('claim-badge--dupe');
    expect(dupeBadgeHtml()).toContain('Dupe');
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

describe('publishDiffFieldChanges', () => {
  it('lists only changed fields', () => {
    const changes = publishDiffFieldChanges(
      { title: 'Old', review_percent: 70 },
      { title: 'New', review_percent: 70 },
    );
    expect(changes).toEqual([{ field: 'title', before: 'Old', after: 'New' }]);
  });
});

describe('formatPublishDiffValue', () => {
  it('formats empty and review percent', () => {
    expect(formatPublishDiffValue('review_percent', '')).toBe('—');
    expect(formatPublishDiffValue('review_percent', 82)).toBe('82%');
  });

  it('truncates long urls', () => {
    const long = `https://example.com/${'a'.repeat(60)}`;
    expect(formatPublishDiffValue('claim_url', long)).toMatch(/…$/);
  });
});

describe('describePublishDiffUpdate', () => {
  it('summarizes field-level deltas', () => {
    const summary = describePublishDiffUpdate({
      id: 'a',
      before: { title: 'Foo Giveaway', review_percent: '' },
      after: { title: 'Foo', review_percent: 82 },
    });
    expect(summary.title).toBe('Foo');
    expect(summary.changes).toHaveLength(2);
    expect(summary.summary).toContain('title: Foo Giveaway → Foo');
    expect(summary.summary).toContain('review %: — → 82%');
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
    expect(diff.updated[0].changes).toEqual([{ field: 'title', before: 'Old', after: 'New' }]);
  });

  it('does not report a re-keyed game as removed+added (same title, different id)', () => {
    // Live feed holds the Epic-keyed entry; pending kept the ITAD copy via "Keep only".
    const live = [{ id: 'epic-rogue-waters', title: 'Rogue Waters', store: 'epic', claim_url: 'https://a' }];
    const pending = [{ id: 'itad-abc123', title: 'Rogue Waters', store: 'epic', claim_url: 'https://a' }];
    const diff = diffPublishFeeds(live, pending);
    expect(diff.removed).toHaveLength(0);
    expect(diff.added).toHaveLength(0);
    expect(diff.updated).toHaveLength(0);
  });

  it('reconciles re-keyed games by steam_appid even when titles differ slightly', () => {
    const live = [{ id: 'epic-x', title: 'Foo: The Game', steam_appid: 42, store: 'epic', claim_url: 'https://a' }];
    const pending = [{ id: 'itad-y', title: 'Foo The Game (Steam) Giveaway', steam_appid: 42, store: 'steam', claim_url: 'https://a' }];
    const diff = diffPublishFeeds(live, pending);
    expect(diff.removed).toHaveLength(0);
    expect(diff.added).toHaveLength(0);
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
