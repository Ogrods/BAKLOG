/**
 * First Steam success enrich offer: gates, modal, bootstrap wiring.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  HLTB_MODAL_UNCHECKED_MIN,
  shouldConfirmHltbRun,
} from '../js/hltb-estimate-modal.js';

describe('shouldOfferSteamEnrich', () => {
  let shouldOfferSteamEnrich;

  beforeEach(async () => {
    vi.resetModules();
    ({ shouldOfferSteamEnrich } = await import('../js/steam-enrich-offer.js'));
  });

  it('skips when offer already seen', () => {
    expect(
      shouldOfferSteamEnrich({
        prefs: { steamEnrichOfferSeen: true, autoEnrichOnAdd: false },
        libraryGames: [{ store: 'steam', id: '1' }],
      }),
    ).toBe(false);
  });

  it('skips when library has no Steam games', () => {
    expect(
      shouldOfferSteamEnrich({
        prefs: { steamEnrichOfferSeen: false },
        libraryGames: [{ store: 'gog', id: '1' }],
      }),
    ).toBe(false);
  });

  it('skips when enrich lane is busy', () => {
    expect(
      shouldOfferSteamEnrich({
        prefs: { steamEnrichOfferSeen: false },
        libraryGames: [{ store: 'steam', id: '1' }],
        enrichBusy: true,
      }),
    ).toBe(false);
  });

  it('offers when Steam games exist and offer unseen', () => {
    expect(
      shouldOfferSteamEnrich({
        prefs: { steamEnrichOfferSeen: false, autoEnrichOnAdd: false },
        libraryGames: [{ store: 'steam', id: '1' }],
        enrichBusy: false,
      }),
    ).toBe(true);
  });
});

describe('markSteamEnrichOfferSeenIfNeeded', () => {
  let markSteamEnrichOfferSeenIfNeeded;
  let savePrefs;

  beforeEach(async () => {
    vi.resetModules();
    const prefsMod = await import('../js/prefs.js');
    savePrefs = vi.spyOn(prefsMod, 'savePrefs').mockImplementation(() => {});
    ({ markSteamEnrichOfferSeenIfNeeded } = await import('../js/steam-enrich-offer.js'));
  });

  afterEach(() => {
    savePrefs?.mockRestore();
  });

  it('quietly marks seen when autoEnrichOnAdd already true', () => {
    const prefs = { steamEnrichOfferSeen: false, autoEnrichOnAdd: true };
    expect(markSteamEnrichOfferSeenIfNeeded(prefs)).toBe(true);
    expect(prefs.steamEnrichOfferSeen).toBe(true);
    expect(savePrefs).toHaveBeenCalled();
  });

  it('does nothing when auto enrich is still off', () => {
    const prefs = { steamEnrichOfferSeen: false, autoEnrichOnAdd: false };
    expect(markSteamEnrichOfferSeenIfNeeded(prefs)).toBe(false);
    expect(prefs.steamEnrichOfferSeen).toBe(false);
  });
});

describe('confirmSteamEnrichOffer markup', () => {
  afterEach(() => {
    document.getElementById('steamEnrichOfferModal')?.remove();
  });

  it('uses body/actions layout and dismisses on Not now', async () => {
    const { confirmSteamEnrichOffer } = await import('../js/steam-enrich-offer.js');
    const pending = confirmSteamEnrichOffer({ unchecked: 10, noMatch: 0 });
    const modal = document.getElementById('steamEnrichOfferModal');
    expect(modal).toBeTruthy();
    const html = modal.innerHTML;
    expect(html).toContain('app-modal-body');
    expect(html).toContain('app-modal-actions');
    expect(html).not.toContain('mt-5');
    expect(html).not.toMatch(/\u2014/);
    expect(modal.querySelector('.steam-enrich-offer-dismiss')).toBeTruthy();
    expect(modal.querySelector('.steam-enrich-offer-run')).toBeTruthy();
    expect(modal.textContent).not.toMatch(/HowLongToBeat alone/i);
    modal.querySelector('.steam-enrich-offer-dismiss')?.click();
    await expect(pending).resolves.toBe(false);
  });

  it('folds HLTB ETA when pending is large', async () => {
    const { confirmSteamEnrichOffer } = await import('../js/steam-enrich-offer.js');
    const unchecked = HLTB_MODAL_UNCHECKED_MIN + 1;
    expect(shouldConfirmHltbRun({ unchecked, noMatch: 0 })).toBe(true);
    const pending = confirmSteamEnrichOffer({ unchecked, noMatch: 0 });
    const modal = document.getElementById('steamEnrichOfferModal');
    expect(modal?.textContent).toMatch(/HowLongToBeat alone/i);
    expect(modal?.textContent).toMatch(/Rough ETA/i);
    modal.querySelector('.steam-enrich-offer-run')?.click();
    await expect(pending).resolves.toBe(true);
  });

  it('accepts Enrich library', async () => {
    const { confirmSteamEnrichOffer } = await import('../js/steam-enrich-offer.js');
    const pending = confirmSteamEnrichOffer({ unchecked: 5, noMatch: 0 });
    document.querySelector('.steam-enrich-offer-run')?.click();
    await expect(pending).resolves.toBe(true);
  });
});

describe('maybeShowSteamEnrichOffer', () => {
  let state;
  let maybeShowSteamEnrichOffer;
  let savePrefs;

  beforeEach(async () => {
    vi.resetModules();
    const prefsMod = await import('../js/prefs.js');
    savePrefs = vi.spyOn(prefsMod, 'savePrefs').mockImplementation(() => {});
    ({ state } = await import('../js/state.js'));
    ({ maybeShowSteamEnrichOffer } = await import('../js/steam-enrich-offer.js'));
    state.prefs = {
      steamEnrichOfferSeen: false,
      autoEnrichOnAdd: false,
    };
    state.allGames = [{ store: 'steam', id: '42', name: 'Test' }];
  });

  afterEach(() => {
    document.getElementById('steamEnrichOfferModal')?.remove();
    savePrefs?.mockRestore();
  });

  it('skips empty non-Steam library', async () => {
    const result = await maybeShowSteamEnrichOffer({
      libraryGames: [],
      confirmFn: async () => true,
      runEnrichBootstrap: vi.fn(),
      savePrefs: () => {},
    });
    expect(result).toBe('skipped');
  });

  it('quietly marks seen when auto enrich already on', async () => {
    state.prefs.autoEnrichOnAdd = true;
    const runEnrichBootstrap = vi.fn();
    const result = await maybeShowSteamEnrichOffer({
      prefs: state.prefs,
      confirmFn: async () => true,
      runEnrichBootstrap,
      savePrefs: () => {
        state.prefs.steamEnrichOfferSeen = true;
      },
    });
    expect(result).toBe('seen-quiet');
    expect(state.prefs.steamEnrichOfferSeen).toBe(true);
    expect(runEnrichBootstrap).not.toHaveBeenCalled();
  });

  it('dismiss marks seen without enabling auto enrich or bootstrap', async () => {
    const runEnrichBootstrap = vi.fn();
    const result = await maybeShowSteamEnrichOffer({
      prefs: state.prefs,
      confirmFn: async () => false,
      runEnrichBootstrap,
      savePrefs: () => {},
      hltbPending: { unchecked: 0, noMatch: 0 },
    });
    expect(result).toBe('dismissed');
    expect(state.prefs.steamEnrichOfferSeen).toBe(true);
    expect(state.prefs.autoEnrichOnAdd).toBe(false);
    expect(runEnrichBootstrap).not.toHaveBeenCalled();
  });

  it('accept enables auto enrich and runs bootstrap', async () => {
    const runEnrichBootstrap = vi.fn().mockResolvedValue(true);
    const result = await maybeShowSteamEnrichOffer({
      prefs: state.prefs,
      confirmFn: async () => true,
      runEnrichBootstrap,
      savePrefs: () => {},
      hltbPending: { unchecked: 0, noMatch: 0 },
      stateFor: () => null,
    });
    expect(result).toBe('enriched');
    expect(state.prefs.steamEnrichOfferSeen).toBe(true);
    expect(state.prefs.autoEnrichOnAdd).toBe(true);
    expect(runEnrichBootstrap).toHaveBeenCalledTimes(1);
    expect(runEnrichBootstrap.mock.calls[0][0].reason).toBe('steam-first-offer');
  });

  it('skips when enrich lane busy', async () => {
    const result = await maybeShowSteamEnrichOffer({
      prefs: state.prefs,
      enrichBusy: true,
      confirmFn: async () => true,
      runEnrichBootstrap: vi.fn(),
      savePrefs: () => {},
    });
    expect(result).toBe('skipped');
  });
});

describe('runEnrichBootstrap', () => {
  let state;
  let runEnrichBootstrap;

  beforeEach(async () => {
    vi.resetModules();
    // Import via fetcher-health (same as auto-enrich tests) so wireFetcherAutoRefresh
    // runs after fetcher-auto-refresh finishes initializing - direct import races the
    // claimable → dashboard → fetcher-health cycle.
    ({ state } = await import('../js/state.js'));
    ({ runEnrichBootstrap } = await import('../js/fetcher-health.js'));
    state.prefs = { autoEnrichOnAdd: false };
  });

  it('queues enrichers without requiring newCount or autoEnrichOnAdd', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    const appendLine = vi.fn();
    const sources = [
      { key: 'steamReviews', missingRequirements: [] },
      { key: 'steamTags', missingRequirements: [] },
      { key: 'steamCovers', missingRequirements: [] },
      { key: 'protondb', missingRequirements: [] },
      { key: 'hltb', missingRequirements: [] },
    ];
    const ok = await runEnrichBootstrap({
      isApiAvailable: () => true,
      now: Date.now() + 90_000,
      runFn,
      waitForQueueSlot: async () => {},
      loadFetcherSources: async () => {},
      sources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      appendLine,
      reason: 'steam-first-offer',
    });
    expect(ok).toBe(true);
    expect(runFn.mock.calls.map((c) => c[0])).toEqual([
      'steamReviews',
      'steamTags',
      'steamCovers',
      'protondb',
      'hltb',
    ]);
    expect(appendLine).toHaveBeenCalledWith(
      expect.stringContaining('enrich-bootstrap: steam-first-offer'),
      'meta',
    );
  });
});

describe('steam enrich offer spacing hygiene', () => {
  it('does not use mt-5 in steam enrich offer modal', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const root = path.resolve(import.meta.dirname, '..');
    const src = fs.readFileSync(path.join(root, 'js/steam-enrich-offer.js'), 'utf8');
    expect(src).not.toMatch(/\bmt-5\b/);
    expect(src).not.toMatch(/\u2014/);
  });
});
