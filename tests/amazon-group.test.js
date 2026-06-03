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
