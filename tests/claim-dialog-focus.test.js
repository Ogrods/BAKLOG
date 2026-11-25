/**
 * Claim dialog openers trap focus and restore it on close.
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';

vi.mock('../js/auth-gate.js', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    isPro: () => false,
    proFeaturesUnlocked: () => false,
  };
});

import { state } from '../js/state.js';
import {
  openClaimDetail,
  closeClaimDetail,
  openHiddenClaimsModal,
  closeHiddenClaimsModal,
} from '../js/claimable.js';

describe('claim dialog focus trap', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button id="opener">Open</button>
      <dialog id="claimDetailDialog"></dialog>
      <dialog id="claimHiddenDialog"></dialog>
      <dialog id="claimPurgeConfirmDialog"></dialog>
    `;
    state.personal = {};
    state.ownedNormNames = new Set();
    state.claimableFeed = {
      items: [
        {
          id: 'c1',
          store: 'epic',
          title: 'Free Game',
          claim_url: 'https://store.epicgames.com/p/free-game',
          ends_at: '2099-01-01T00:00:00Z',
        },
      ],
    };
    state.claimableNow = state.claimableFeed.items;
  });

  afterEach(() => {
    closeClaimDetail();
    closeHiddenClaimsModal();
    document.body.innerHTML = '';
  });

  it('restores focus to the opener when the detail dialog closes', () => {
    const opener = document.getElementById('opener');
    opener.focus();
    expect(document.activeElement).toBe(opener);

    openClaimDetail('c1');
    const dlg = document.getElementById('claimDetailDialog');
    expect(dlg.open).toBe(true);
    expect(document.activeElement).not.toBe(opener);

    closeClaimDetail();
    expect(dlg.open).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it('traps focus inside the hidden-claims dialog', () => {
    state.personal.__dismissedClaims = { c1: Date.now() };
    const opener = document.getElementById('opener');
    opener.focus();
    openHiddenClaimsModal();
    const dlg = document.getElementById('claimHiddenDialog');
    expect(dlg.open).toBe(true);
    expect(dlg.contains(document.activeElement)).toBe(true);
    closeHiddenClaimsModal();
    expect(document.activeElement).toBe(opener);
  });
});
