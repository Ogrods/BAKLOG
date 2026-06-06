import { describe, expect, it } from 'vitest';
import { groupRepFor, combinedGroupStatus, groupRailPill } from '../js/connections.js';

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

  it('content groups follow library status, not wishlist', () => {
    expect(
      combinedGroupStatus([
        { key: 'xbox', status: 'disconnected' },
        { key: 'xbox_wishlist', status: 'connected' },
      ], 'xbox'),
    ).toBe('disconnected');
    expect(
      combinedGroupStatus([
        { key: 'xbox', status: 'expired' },
        { key: 'xbox_wishlist', status: 'connected' },
      ], 'xbox'),
    ).toBe('expired');
    expect(
      combinedGroupStatus([
        { key: 'xbox', status: 'connected' },
        { key: 'xbox_wishlist', status: 'connected' },
      ], 'xbox'),
    ).toBe('connected');
  });
});

describe('groupRailPill — content group (library + wishlist) summary', () => {
  const xbox = (lib, wl) => groupRailPill(
    [{ key: 'xbox', status: lib }, { key: 'xbox_wishlist', status: wl }],
    'xbox',
  );

  it('is null for source groups (any one member is enough)', () => {
    expect(groupRailPill(
      [{ key: 'amazon', status: 'disconnected' }, { key: 'amazon_web', status: 'connected' }],
      'amazon',
    )).toBeNull();
  });

  it('is null for ungrouped keys and empty members', () => {
    expect(groupRailPill([{ key: 'steam', status: 'connected' }], 'steam')).toBeNull();
    expect(groupRailPill([], 'xbox')).toBeNull();
  });

  it('all members connected -> green Connected pill', () => {
    expect(xbox('connected', 'connected')).toEqual({
      cls: 'conn-pill conn-pill--ok', label: 'Connected', dotState: 'connected',
    });
  });

  it('nothing set up (all disconnected/unavailable) -> grey Not connected', () => {
    expect(xbox('disconnected', 'disconnected')).toEqual({
      cls: 'conn-pill conn-pill--off', label: 'Not connected', dotState: 'disconnected',
    });
    expect(xbox('unavailable', 'disconnected')).toEqual({
      cls: 'conn-pill conn-pill--off', label: 'Not connected', dotState: 'disconnected',
    });
  });

  it('one member expired -> amber "1 expired" (either side)', () => {
    const expected = { cls: 'conn-pill conn-pill--warn', label: '1 expired', dotState: 'expired' };
    expect(xbox('connected', 'expired')).toEqual(expected);
    expect(xbox('expired', 'connected')).toEqual(expected);
  });

  it('one member not connected -> amber "1 not connected"', () => {
    expect(xbox('connected', 'disconnected')).toEqual({
      cls: 'conn-pill conn-pill--warn', label: '1 not connected', dotState: 'expired',
    });
  });

  it('one member unverified -> amber "1 unverified"', () => {
    expect(xbox('connected', 'unverified')).toEqual({
      cls: 'conn-pill conn-pill--warn', label: '1 unverified', dotState: 'expired',
    });
  });

  it('both expired -> amber "2 expired"', () => {
    expect(xbox('expired', 'expired')).toEqual({
      cls: 'conn-pill conn-pill--warn', label: '2 expired', dotState: 'expired',
    });
  });

  it('mixed problems -> amber, severity-ordered, dot-separated', () => {
    expect(xbox('expired', 'disconnected').label).toBe('1 expired \u00b7 1 not connected');
    expect(xbox('disconnected', 'expired').label).toBe('1 expired \u00b7 1 not connected');
  });

  it('every library×wishlist combination yields a defined pill', () => {
    const states = ['connected', 'expired', 'disconnected', 'unverified', 'unavailable'];
    for (const lib of states) {
      for (const wl of states) {
        const pill = xbox(lib, wl);
        expect(pill).not.toBeNull();
        expect(typeof pill.label).toBe('string');
        expect(pill.label.length).toBeGreaterThan(0);
        expect(pill.cls).toMatch(/conn-pill--(ok|warn|off)/);
      }
    }
  });
});
