/**
 * Tests for js/affiliate.js — store-link tagging only (ITAD deal URLs untouched).
 *
 * Going live is a single paste step: a program activates when its
 * AFFILIATE_CREDENTIALS entry is filled (param value, or deeplink template
 * containing {url}). There is no separate enabled flag.
 */

import { describe, expect, it, afterEach } from 'vitest';
import {
  affiliateUrl,
  AFFILIATE_RULES,
  AFFILIATE_CREDENTIALS,
  hasLiveAffiliates,
  liveAffiliateShops,
} from '../js/affiliate.js';

/** Snapshot all credentials so each test restores the shipped (empty) state. */
function snapshotCreds() {
  return { ...AFFILIATE_CREDENTIALS };
}

function restoreCreds(snap) {
  for (const key of Object.keys(AFFILIATE_CREDENTIALS)) delete AFFILIATE_CREDENTIALS[key];
  Object.assign(AFFILIATE_CREDENTIALS, snap);
}

describe('affiliateUrl', () => {
  const baseline = snapshotCreds();

  afterEach(() => {
    restoreCreds(baseline);
  });

  it('ships with every program disabled', () => {
    for (const value of Object.values(AFFILIATE_CREDENTIALS)) {
      expect(value).toBe('');
    }
    expect(hasLiveAffiliates()).toBe(false);
    expect(liveAffiliateShops()).toEqual([]);
  });

  it('passes through Steam URLs (no program)', () => {
    const url = 'https://store.steampowered.com/app/570/';
    expect(affiliateUrl(url)).toBe(url);
  });

  it('passes through ITAD redirect URLs (ToS-locked)', () => {
    AFFILIATE_CREDENTIALS.gog = 'https://track.example.com/?dest={url}';
    const url = 'https://next.isthereanydeal.com/link/018d9386-7132-719b-89e1-e11b8c591ee7/';
    expect(affiliateUrl(url)).toBe(url);
  });

  it('passes through when all rules are disabled', () => {
    const url = 'https://www.gog.com/en/game/foo';
    expect(affiliateUrl(url)).toBe(url);
  });

  it('passes through non-http values', () => {
    expect(affiliateUrl('')).toBe('');
    expect(affiliateUrl(null)).toBe(null);
    expect(affiliateUrl('not-a-url')).toBe('not-a-url');
    expect(affiliateUrl('javascript:alert(1)')).toBe('javascript:alert(1)');
  });

  it('activates a param program when its value is pasted in', () => {
    AFFILIATE_CREDENTIALS.epic = 'BAKLOG';
    const url = 'https://store.epicgames.com/en-US/p/foo';
    const out = affiliateUrl(url);
    expect(out).toContain('epic_creator_id=BAKLOG');
    expect(out.startsWith(url.split('?')[0])).toBe(true);
    expect(hasLiveAffiliates()).toBe(true);
    expect(liveAffiliateShops()).toContain('Epic Games Store');
  });

  it('is idempotent for param rules', () => {
    AFFILIATE_CREDENTIALS.epic = 'BAKLOG';
    const url = 'https://store.epicgames.com/en-US/p/foo?epic_creator_id=BAKLOG';
    expect(affiliateUrl(url)).toBe(url);
  });

  it('tags itch.io URLs (and creator subdomains) with the ac code', () => {
    AFFILIATE_CREDENTIALS.itch = 'eob7ZQcpthHDp';
    const root = affiliateUrl('https://itch.io/games/free');
    expect(new URL(root).searchParams.get('ac')).toBe('eob7ZQcpthHDp');

    const creator = affiliateUrl('https://somedev.itch.io/cool-game');
    expect(new URL(creator).searchParams.get('ac')).toBe('eob7ZQcpthHDp');

    expect(liveAffiliateShops()).toContain('itch.io');
    // Idempotent: re-tagging an already-tagged URL is a no-op.
    expect(affiliateUrl(creator)).toBe(creator);
  });

  it('tags itch free-claim and fetcher store_url shapes', () => {
    AFFILIATE_CREDENTIALS.itch = 'eob7ZQcpthHDp';
    const claim = affiliateUrl('https://s-xavier-uy.itch.io/another-world-adventures');
    expect(new URL(claim).searchParams.get('ac')).toBe('eob7ZQcpthHDp');

    const local = affiliateUrl('https://dev.itch.io/local-game');
    expect(new URL(local).searchParams.get('ac')).toBe('eob7ZQcpthHDp');
  });

  it('wraps URL in deeplink template when a {url} template is pasted in', () => {
    AFFILIATE_CREDENTIALS.gog = 'https://track.example.com/?dest={url}';
    const url = 'https://www.gog.com/en/game/bar';
    expect(affiliateUrl(url)).toBe(`https://track.example.com/?dest=${encodeURIComponent(url)}`);
  });

  it('keeps a deeplink program OFF when the template lacks {url}', () => {
    AFFILIATE_CREDENTIALS.gog = 'https://track.example.com/no-placeholder';
    const url = 'https://www.gog.com/en/game/bar';
    expect(affiliateUrl(url)).toBe(url);
    expect(hasLiveAffiliates()).toBe(false);
  });

  it('treats whitespace-only credentials as unset', () => {
    AFFILIATE_CREDENTIALS.epic = '   ';
    const url = 'https://store.epicgames.com/en-US/p/foo';
    expect(affiliateUrl(url)).toBe(url);
    expect(hasLiveAffiliates()).toBe(false);
  });

  it('is idempotent for deeplink rules', () => {
    AFFILIATE_CREDENTIALS.humble = 'https://humble.example.com/?u={url}';
    const url = 'https://www.humblebundle.com/store/game';
    const tagged = affiliateUrl(url);
    expect(affiliateUrl(tagged)).toBe(tagged);
  });

  it('matches regional host suffixes', () => {
    AFFILIATE_CREDENTIALS.gog = 'https://track.example.com/?dest={url}';
    // gamesplanet program is unset — should pass through
    const url = 'https://us.gamesplanet.com/game/123';
    expect(affiliateUrl(url)).toBe(url);

    const gogUrl = 'https://embed.gog.com/foo';
    expect(affiliateUrl(gogUrl)).toBe(`https://track.example.com/?dest=${encodeURIComponent(gogUrl)}`);
  });

  it('merges param into existing query string', () => {
    AFFILIATE_CREDENTIALS.epic = 'BAKLOG';
    const url = 'https://store.epicgames.com/en-US/p/foo?lang=en';
    const out = affiliateUrl(url);
    const u = new URL(out);
    expect(u.searchParams.get('epic_creator_id')).toBe('BAKLOG');
    expect(u.searchParams.get('lang')).toBe('en');
  });

  it('exposes a credential slot for every rule', () => {
    for (const rule of AFFILIATE_RULES) {
      expect(AFFILIATE_CREDENTIALS).toHaveProperty(rule.id);
    }
  });
});
