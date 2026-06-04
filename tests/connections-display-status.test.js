import { describe, it, expect } from 'vitest';
import { displayStatus } from '../js/connections.js';

const STATUS_LABEL = {
  connected: 'Connected',
  unverified: 'Unverified',
  disconnected: 'Not connected',
  expired: 'Session expired',
};

describe('displayStatus', () => {
  it('keeps expired as its own pill state', () => {
    expect(displayStatus('expired')).toBe('expired');
  });

  it('passes through the primary states', () => {
    expect(displayStatus('connected')).toBe('connected');
    expect(displayStatus('unverified')).toBe('unverified');
    expect(displayStatus('disconnected')).toBe('disconnected');
  });

  it('maps pill labels for connected, unverified, disconnected, and expired', () => {
    for (const key of ['connected', 'unverified', 'disconnected', 'expired']) {
      const pill = displayStatus(key);
      expect(STATUS_LABEL[pill]).toBeDefined();
    }
    expect(STATUS_LABEL[displayStatus('expired')]).toBe('Session expired');
  });
});
