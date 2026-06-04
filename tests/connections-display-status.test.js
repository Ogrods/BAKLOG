import { describe, it, expect } from 'vitest';
import { displayStatus } from '../js/connections.js';

const STATUS_LABEL = {
  connected: 'Connected',
  unverified: 'Unverified',
  disconnected: 'Not connected',
};

describe('displayStatus', () => {
  it('maps expired to disconnected for pill display', () => {
    expect(displayStatus('expired')).toBe('disconnected');
  });

  it('passes through the three primary states', () => {
    expect(displayStatus('connected')).toBe('connected');
    expect(displayStatus('unverified')).toBe('unverified');
    expect(displayStatus('disconnected')).toBe('disconnected');
  });

  it('produces only the three visible pill labels for primary states', () => {
    for (const key of ['connected', 'unverified', 'disconnected']) {
      const pill = displayStatus(key);
      expect(STATUS_LABEL[pill]).toBeDefined();
      expect(['Connected', 'Unverified', 'Not connected']).toContain(STATUS_LABEL[pill]);
    }
    expect(STATUS_LABEL[displayStatus('expired')]).toBe('Not connected');
  });
});
