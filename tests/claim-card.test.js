/**
 * Parity tests for the shared "Claimable Now" renderer (js/claim-card.js).
 *
 * The live app (js/claimable.js) and the admin publish preview (admin/admin.js
 * iframe) both render through claimableModuleMarkup, so these assertions lock
 * the markup features a brand-new user actually sees — and that the preview is
 * guaranteed to match: source badges, feed attribution, appid/title dedupe by
 * source precedence, ends_at sort, review clamp, and cover URL safety.
 */
import { describe, expect, it, beforeAll } from 'vitest';
import {
  claimableModuleMarkup,
  claimCardHtml,
  dedupeClaims,
  sortClaims,
  sanitizeBlurb,
} from '../js/claim-card.js';

beforeAll(() => {
  // covers.js (not imported here) normally installs these globals; the markup
  // helpers call coverLandscapeAttr at render time, so stub it.
  window.coverLandscapeAttr = () => '';
});

describe('claimableModuleMarkup', () => {
  it('renders the source badge for a single hero claim', () => {
    const html = claimableModuleMarkup([
      { id: 'epic-foo', store: 'epic', title: 'Foo', claim_url: 'https://e/x', source: 'epic', header_image: 'https://cdn/x.jpg' },
    ]);
    expect(html).toContain('claim-hero-card');
    expect(html).toContain('claim-source');
    expect(html).toContain('via Epic');
  });

  it('renders the source badge on every row in the multi-claim layout', () => {
    const html = claimableModuleMarkup([
      { id: 'epic-a', store: 'epic', title: 'A', claim_url: 'https://e/a', source: 'epic', ends_at: '2099-01-01T00:00:00Z' },
      { id: 'gp-b', store: 'gog', title: 'B', claim_url: 'https://g/b', source: 'gamerpower', ends_at: '2099-02-01T00:00:00Z' },
    ]);
    expect(html).toContain('claim-rows');
    expect(html).toContain('via Epic');
    expect(html).toContain('via GamerPower');
  });

  it('renders the GamerPower attribution footer when attribution is provided', () => {
    const html = claimableModuleMarkup(
      [
        { id: 'a', store: 'epic', title: 'A', claim_url: 'https://e/a', ends_at: '2099-01-01T00:00:00Z' },
        { id: 'b', store: 'gog', title: 'B', claim_url: 'https://g/b', ends_at: '2099-02-01T00:00:00Z' },
      ],
      { attribution: ['GamerPower.com'] },
    );
    expect(html).toContain('claim-attribution');
    expect(html).toContain('GamerPower.com');
  });

  it('omits the attribution footer when none is provided', () => {
    const html = claimableModuleMarkup([
      { id: 'a', store: 'epic', title: 'A', claim_url: 'https://e/a', ends_at: '2099-01-01T00:00:00Z' },
      { id: 'b', store: 'gog', title: 'B', claim_url: 'https://g/b', ends_at: '2099-02-01T00:00:00Z' },
    ]);
    expect(html).not.toContain('claim-attribution');
  });

  it('caps visible rows and shows a "+N more" toggle', () => {
    const items = Array.from({ length: 7 }, (_, i) => ({
      id: `c${i}`, store: 'epic', title: `Game ${i}`, claim_url: `https://e/${i}`,
      ends_at: `2099-01-0${i + 1}T00:00:00Z`,
    }));
    const html = claimableModuleMarkup(items, { visibleCount: 5 });
    expect(html).toContain('data-claim-show-more');
    expect(html).toContain('+2 more');
  });
});

describe('claimCardHtml safety + clamping', () => {
  it('clamps review_percent into 0–100', () => {
    const html = claimCardHtml({ id: 'a', store: 'steam', title: 'A', claim_url: 'https://s/a', review_percent: 150 });
    expect(html).toContain('100%');
    expect(html).not.toContain('150%');
  });

  it('drops an unsafe header_image to the gradient placeholder', () => {
    const html = claimCardHtml({ id: 'a', store: 'steam', title: 'A', claim_url: 'https://s/a', header_image: 'javascript:alert(1)' });
    expect(html).toContain('claim-hero-cover-fallback');
    expect(html).not.toContain('javascript:alert(1)');
  });

  it('strips bare URLs from ITAD blurbs', () => {
    expect(sanitizeBlurb('Grab it at https://itad.example/x now')).not.toContain('http');
  });
});

describe('dedupe + sort (getVisibleClaims internals)', () => {
  it('collapses the same game from multiple sources by source precedence (epic wins)', () => {
    const items = [
      { id: 'gp', store: 'gog', title: 'Same Game', claim_url: 'https://g/x', source: 'gamerpower' },
      { id: 'epic', store: 'epic', title: 'Same Game', claim_url: 'https://e/x', source: 'epic' },
    ];
    const out = dedupeClaims(items);
    expect(out).toHaveLength(1);
    expect(out[0].source).toBe('epic');
  });

  it('dedupes by steam_appid across differing titles', () => {
    const items = [
      { id: 'a', store: 'steam', title: 'Game (Steam) Giveaway', claim_url: 'https://s/a', steam_appid: 42, source: 'gamerpower' },
      { id: 'b', store: 'steam', title: 'Game', claim_url: 'https://s/b', steam_appid: 42, source: 'epic' },
    ];
    expect(dedupeClaims(items)).toHaveLength(1);
  });

  it('sorts by ends_at then title', () => {
    const items = [
      { id: 'b', store: 'epic', title: 'Bbb', claim_url: 'https://e/b', ends_at: '2099-03-01T00:00:00Z' },
      { id: 'a', store: 'epic', title: 'Aaa', claim_url: 'https://e/a', ends_at: '2099-01-01T00:00:00Z' },
      { id: 'noend', store: 'epic', title: 'Zzz', claim_url: 'https://e/z' },
    ];
    const out = sortClaims([...items]);
    expect(out.map(c => c.id)).toEqual(['a', 'b', 'noend']);
  });
});
