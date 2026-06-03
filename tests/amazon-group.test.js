import { describe, expect, it } from 'vitest';
import { groupRepFor, combinedGroupStatus } from '../js/connections.js';

describe('groupRepFor', () => {
  it('maps amazon_web and amazon to the amazon group', () => {
    expect(groupRepFor('amazon_web')).toBe('amazon');
    expect(groupRepFor('amazon')).toBe('amazon');
  });

  it('passes through ungrouped keys', () => {
    expect(groupRepFor('steam')).toBe('steam');
    expect(groupRepFor('gog')).toBe('gog');
  });
});

describe('combinedGroupStatus', () => {
  it('amazon group can stay connected when only the launcher member is disconnected', () => {
    expect(
      combinedGroupStatus([
        { key: 'amazon', status: 'disconnected' },
        { key: 'amazon_web', status: 'connected' },
      ]),
    ).toBe('connected');
  });

  it('picks the highest-priority status across members', () => {
    expect(
      combinedGroupStatus([
        { status: 'disconnected' },
        { status: 'connected' },
      ]),
    ).toBe('connected');
    expect(
      combinedGroupStatus([
        { status: 'unverified' },
        { status: 'expired' },
      ]),
    ).toBe('expired');
    expect(
      combinedGroupStatus([
        { status: 'unavailable' },
        { status: 'disconnected' },
      ]),
    ).toBe('disconnected');
  });
});
