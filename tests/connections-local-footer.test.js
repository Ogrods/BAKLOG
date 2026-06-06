import { describe, it, expect } from 'vitest';
import { localProviderFooterCopy } from '../js/connections.js';

describe('localProviderFooterCopy', () => {
  it('uses provider-specific copy for dual-source locals', () => {
    expect(localProviderFooterCopy('amazon', true)).toContain('Amazon Games');
    expect(localProviderFooterCopy('gog_galaxy', true)).toContain('GOG Galaxy');
    expect(localProviderFooterCopy('itch_local', true)).toContain('itch desktop');
    expect(localProviderFooterCopy('gog_galaxy', false)).toContain('GOG (web)');
    expect(localProviderFooterCopy('itch_local', false)).toContain('API key');
  });
});
