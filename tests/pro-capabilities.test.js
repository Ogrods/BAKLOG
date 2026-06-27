/** hasCapability reads resolved flags from /api/config capabilities map. */
import { describe, expect, it, beforeEach } from 'vitest';
import {
  capabilityStatus,
  hasCapability,
  listComingCapabilities,
  listLiveCapabilities,
  setCapabilitiesFromConfig,
} from '../js/pro-capabilities.js';

describe('pro-capabilities', () => {
  beforeEach(() => {
    setCapabilitiesFromConfig({
      queue_bulk_refresh: { status: 'live', enabled: true },
      cloud_sync_mirror: { status: 'coming', enabled: false },
      no_ads: { status: 'live', enabled: false },
    });
  });

  it('hasCapability returns enabled flag from config', () => {
    expect(hasCapability('queue_bulk_refresh')).toBe(true);
    expect(hasCapability('no_ads')).toBe(false);
    expect(hasCapability('cloud_sync_mirror')).toBe(false);
  });

  it('capabilityStatus distinguishes live vs coming', () => {
    expect(capabilityStatus('queue_bulk_refresh')).toBe('live');
    expect(capabilityStatus('cloud_sync_mirror')).toBe('coming');
  });

  it('listLiveCapabilities only includes enabled live caps', () => {
    expect(listLiveCapabilities()).toEqual(['queue_bulk_refresh']);
  });

  it('listComingCapabilities lists coming status caps', () => {
    expect(listComingCapabilities()).toContain('cloud_sync_mirror');
  });
});
