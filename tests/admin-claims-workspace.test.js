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
  isStaleAutoClaim,
  AUTO_HIDE_AGE_MS,
  looksLikeBonusClaim,
  missingPublishFields,
  normTitleKey,
  pendingNeedsPublishEnrichment,
  reindexToFeedOrder,
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

  it('treats key-matched rows as selected when id differs', () => {
    const approvedKeys = new Set(['title:rogue waters']);
    const st = claimRowStatus(
      {
        id: 'gamerpower-new',
        store: 'epic',
        title: 'Rogue Waters',
        claim_url: 'https://x',
        ends_at: '2026-12-01T00:00:00Z',
      },
      { now, approvedIds: new Set(['itad-old']), approvedKeys, isAuto: true },
    );
    expect(st.publishState).toBe('will_publish');
  });
});

describe('normTitleKey', () => {
  it('matches Python norm_title ampersand handling', () => {
    expect(normTitleKey('Mr.Brocco & Co')).toBe('mr brocco and co');
  });
});

describe('pendingNeedsPublishEnrichment', () => {
  it('returns true when pending row lacks cover and live row is also bare', () => {
    const pending = [{ id: 'gp-1', store: 'steam', title: 'Foo', claim_url: 'https://x' }];
    const live = [{ id: 'gp-1', store: 'steam', title: 'Foo', claim_url: 'https://x' }];
    expect(pendingNeedsPublishEnrichment(pending, live)).toBe(true);
  });

  it('returns false when enriched epic row has no steam_appid', () => {
    const pending = [{
      id: 'epic-1',
      store: 'epic',
      title: 'Some Game',
      claim_url: 'https://epic.com/free',
      header_image: 'https://cdn.example/cover.jpg',
      review_percent: 87,
    }];
    expect(pendingNeedsPublishEnrichment(pending, pending)).toBe(false);
  });

  it('returns false when live row carries enrichment for id-matched pending row', () => {
    const pending = [{ id: 'epic-1', store: 'epic', title: 'Some Game', claim_url: 'https://epic.com/free' }];
    const live = [{
      id: 'epic-1',
      store: 'epic',
      title: 'Some Game',
      claim_url: 'https://epic.com/free',
      header_image: 'https://cdn.example/cover.jpg',
      review_percent: 87,
    }];
    expect(pendingNeedsPublishEnrichment(pending, live)).toBe(false);
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

  it('sorts newest by first_seen descending', () => {
    const sorted = sortClaimsItems(
      [
        { id: 'steam-older', first_seen: '2026-06-01T12:00:00+00:00' },
        { id: 'epic-newer', first_seen: '2026-06-10T08:00:00+00:00' },
        { id: 'gog-middle', first_seen: '2026-06-05T00:00:00+00:00' },
      ],
      'newest',
    );
    expect(sorted.map((row) => row.id)).toEqual([
      'epic-newer',
      'gog-middle',
      'steam-older',
    ]);
  });

  it('falls back to id when first_seen is missing', () => {
    const sorted = sortClaimsItems(
      [
        { id: 'amazon-a' },
        { id: 'steam-z' },
      ],
      'newest',
    );
    expect(sorted.map((row) => row.id)).toEqual(['steam-z', 'amazon-a']);
  });

  it('floats a newer first_seen to the top regardless of feed position', () => {
    const sorted = sortClaimsItems(
      [
        { id: 'epic-old', first_seen: '2026-06-11T22:48:59+00:00' },
        { id: 'gamerpower-3684', first_seen: '2026-06-11T22:48:59+00:00' },
        { id: 'gamerpower-3410', first_seen: '2026-06-12T21:29:40+00:00' },
        { id: 'itad-old', first_seen: '2026-06-11T22:48:59+00:00' },
      ],
      'newest',
    );
    expect(sorted[0].id).toBe('gamerpower-3410');
  });

  it('keeps feed order for a same-batch tie instead of burying by id', () => {
    const sorted = sortClaimsItems(
      [
        { id: 'epic-a', first_seen: '2026-06-11T22:48:59+00:00' },
        { id: 'gamerpower-1', first_seen: '2026-06-11T22:48:59+00:00' },
        { id: 'itad-z', first_seen: '2026-06-11T22:48:59+00:00' },
      ],
      'newest',
    );
    // Equal stamps must preserve incoming order; id-desc would put itad-z first.
    expect(sorted.map((row) => row.id)).toEqual(['epic-a', 'gamerpower-1', 'itad-z']);
  });
});

describe('reindexToFeedOrder', () => {
  const feed = [
    { id: 'epic-a', first_seen: '2026-06-11T22:48:59+00:00' },
    { id: 'gamerpower-b', first_seen: '2026-06-11T22:48:59+00:00' },
    { id: 'itad-c', first_seen: '2026-06-11T22:48:59+00:00' },
    { id: 'gamerpower-new', first_seen: '2026-06-12T21:29:40+00:00' },
  ];

  it('returns a restored item to its original feed slot after push-to-end', () => {
    let visible = feed.filter((it) => it.id !== 'gamerpower-b');
    visible = reindexToFeedOrder(visible, feed);
    expect(visible.map((row) => row.id)).toEqual(['epic-a', 'itad-c', 'gamerpower-new']);

    // Simulate restoreHiddenItem: push clone to end, then reindex.
    visible = [...visible, { ...feed[1] }];
    visible = reindexToFeedOrder(visible, feed);
    expect(visible.map((row) => row.id)).toEqual([
      'epic-a',
      'gamerpower-b',
      'itad-c',
      'gamerpower-new',
    ]);
  });

  it('matches sortClaimsItems newest order after hide/restore round-trip', () => {
    let visible = feed.filter((it) => it.id !== 'itad-c');
    visible = reindexToFeedOrder(visible, feed);
    visible = [...visible, { ...feed[2] }];
    visible = reindexToFeedOrder(visible, feed);
    const sorted = sortClaimsItems(visible, 'newest');
    expect(sorted.map((row) => row.id)).toEqual([
      'gamerpower-new',
      'epic-a',
      'gamerpower-b',
      'itad-c',
    ]);
  });

  it('places unblock the same as restore for the same feed id', () => {
    const hiddenId = 'gamerpower-b';
    const afterRestore = reindexToFeedOrder(
      [...feed.filter((it) => it.id !== hiddenId), { ...feed[1] }],
      feed,
    );
    const afterUnblock = reindexToFeedOrder(
      [...feed.filter((it) => it.id !== hiddenId), { ...feed[1] }],
      feed,
    );
    expect(afterRestore.map((row) => row.id)).toEqual(afterUnblock.map((row) => row.id));
  });
});

describe('isStaleAutoClaim', () => {
  const now = Date.parse('2026-06-12T00:00:00+00:00');
  const oldSeen = new Date(now - AUTO_HIDE_AGE_MS - 86400000).toISOString();
  const recentSeen = new Date(now - 86400000).toISOString();

  it('is not stale without a first_seen stamp', () => {
    expect(isStaleAutoClaim({ id: 'a' }, now)).toBe(false);
  });

  it('is not stale when younger than the threshold', () => {
    expect(isStaleAutoClaim({ id: 'a', first_seen: recentSeen }, now)).toBe(false);
  });

  it('is stale when older than a month with no end date', () => {
    expect(isStaleAutoClaim({ id: 'a', first_seen: oldSeen }, now)).toBe(true);
  });

  it('is stale when older than a month and already ended', () => {
    const ended = new Date(now - 86400000).toISOString();
    expect(isStaleAutoClaim({ id: 'a', first_seen: oldSeen, ends_at: ended }, now)).toBe(true);
  });

  it('is NOT stale when the end date is still in the future', () => {
    const future = new Date(now + 7 * 86400000).toISOString();
    expect(isStaleAutoClaim({ id: 'a', first_seen: oldSeen, ends_at: future }, now)).toBe(false);
  });
});

describe('filterClaimsItems stale auto-hide', () => {
  const now = Date.parse('2026-06-12T00:00:00+00:00');
  const oldSeen = new Date(now - AUTO_HIDE_AGE_MS - 86400000).toISOString();
  const recentSeen = new Date(now - 86400000).toISOString();
  const items = [
    { id: 'fresh', store: 'epic', title: 'Fresh', claim_url: 'https://x', first_seen: recentSeen },
    { id: 'stale-unsel', store: 'epic', title: 'StaleUnsel', claim_url: 'https://x', first_seen: oldSeen },
    { id: 'stale-sel', store: 'epic', title: 'StaleSel', claim_url: 'https://x', first_seen: oldSeen },
    { id: 'stale-live', store: 'epic', title: 'StaleLive', claim_url: 'https://x', first_seen: oldSeen, ends_at: new Date(now + 7 * 86400000).toISOString() },
  ];
  const approvedIds = new Set(['stale-sel']);

  it('hides stale unselected rows from the default view', () => {
    const out = filterClaimsItems(items, { approvedIds }, now);
    const ids = out.map((it) => it.id);
    expect(ids).toContain('fresh');
    expect(ids).toContain('stale-sel'); // selected stays
    expect(ids).toContain('stale-live'); // future end date stays
    expect(ids).not.toContain('stale-unsel');
  });

  it('shows only stale rows under the stale filter', () => {
    const out = filterClaimsItems(items, { status: 'stale', approvedIds }, now);
    const ids = out.map((it) => it.id).sort();
    expect(ids).toEqual(['stale-sel', 'stale-unsel']);
  });

  it('does not apply stale auto-hide to explicit filters like unselected', () => {
    const out = filterClaimsItems(items, { status: 'unselected', approvedIds }, now);
    const ids = out.map((it) => it.id);
    expect(ids).toContain('stale-unsel');
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

  it('includes header_image when cover changes', () => {
    const changes = publishDiffFieldChanges(
      { header_image: 'https://example.com/old.jpg' },
      { header_image: 'https://example.com/new.jpg' },
    );
    expect(changes).toEqual([
      { field: 'header_image', before: 'https://example.com/old.jpg', after: 'https://example.com/new.jpg' },
    ]);
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

describe('claimRowStatus manual rows', () => {
  it('marks unchecked manual rows as not selected', () => {
    const st = claimRowStatus(
      { id: 'manual-off', store: 'steam', title: 'Off', claim_url: 'https://x', approved: false },
      { isAuto: false },
    );
    expect(st.publishState).toBe('not_selected');
    expect(st.publishable).toBe(false);
  });

  it('marks default manual rows as will publish', () => {
    const st = claimRowStatus(
      { id: 'manual-on', store: 'steam', title: 'On', claim_url: 'https://x' },
      { isAuto: false },
    );
    expect(st.publishState).toBe('will_publish');
    expect(st.publishable).toBe(true);
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

  it('requires claim_urls for epic_mobile', () => {
    expect(missingPublishFields({
      id: 'epic_mobile-northgard',
      store: 'epic_mobile',
      title: 'Northgard',
    })).toEqual(['claim_urls']);
  });

  it('accepts epic_mobile with one platform url', () => {
    expect(missingPublishFields({
      id: 'epic_mobile-northgard',
      store: 'epic_mobile',
      title: 'Northgard',
      claim_urls: { ios: 'https://apps.apple.com/app/id123' },
    })).toEqual([]);
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
    const stats = computeOverviewStats(items, new Set(['1', '2']), new Set(), [], now);
    expect(stats.total).toBe(3);
    expect(stats.selected).toBe(2);
    expect(stats.expired).toBe(1);
    expect(stats.expiring).toBe(1);
  });

  it('counts pro-only rows from auto and manual pools', () => {
    const now = Date.parse('2026-06-08T12:00:00Z');
    const items = [
      { id: '1', title: 'A', store: 'steam', claim_url: 'x' },
      { id: '2', title: 'B', store: 'epic', claim_url: 'y' },
    ];
    const stats = computeOverviewStats(
      items,
      new Set(['1', '2']),
      new Set(['2']),
      [{ premium_only: true }],
      now,
    );
    expect(stats.proOnly).toBe(2);
  });
});

describe('looksLikeBonusClaim', () => {
  it('flags likely DLC/bonus titles', () => {
    expect(looksLikeBonusClaim('Skins Pack DLC Giveaway')).toBe(true);
    expect(looksLikeBonusClaim('Tell Me Why')).toBe(false);
  });
});

describe('filterClaimsItems premium_only', () => {
  it('filters to pro-only flagged rows', () => {
    const items = [
      { id: '1', title: 'Game', store: 'steam', claim_url: 'x' },
      { id: '2', title: 'DLC Pack', store: 'steam', claim_url: 'y' },
    ];
    const filtered = filterClaimsItems(items, {
      status: 'premium_only',
      approvedIds: new Set(['1', '2']),
      premiumOnlyIds: new Set(['2']),
    });
    expect(filtered.map((it) => it.id)).toEqual(['2']);
  });
});
