import { describe, expect, it } from 'vitest';
import {
  hasValidClaimLinks,
  inferClaimUrlPlatform,
  missingClaimLinkFields,
  normalizeClaimUrls,
} from '../js/claim-links.js';

describe('claim-links', () => {
  it('normalizes platform urls', () => {
    expect(normalizeClaimUrls({
      ios: 'https://apps.apple.com/app/id1',
      android: 'not-a-url',
    })).toEqual({ ios: 'https://apps.apple.com/app/id1' });
  });

  it('infers platform from store urls', () => {
    expect(inferClaimUrlPlatform('https://apps.apple.com/app/id123')).toBe('ios');
    expect(inferClaimUrlPlatform('https://play.google.com/store/apps/details?id=abc')).toBe('android');
    expect(inferClaimUrlPlatform('https://store.epicgames.com/en-US/p/foo')).toBeNull();
  });

  it('validates epic_mobile link requirements', () => {
    expect(hasValidClaimLinks({
      store: 'epic_mobile',
      claim_urls: { android: 'https://play.google.com/store/apps/details?id=x' },
    })).toBe(true);
    expect(missingClaimLinkFields({ store: 'epic_mobile' })).toEqual(['claim_urls']);
  });
});
