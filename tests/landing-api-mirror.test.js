/** Tests for landing/api/_mirror-helpers.js (hosted mirror Pro + profile discovery). */
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import {
  ALLOWED_ARTIFACT,
  extractPlan,
  isCompProEmail,
  isProUser,
  isValidProfileId,
  loadCompProEmails,
  parseMirrorListRows,
  resolveArtifactProfile,
} from '../landing/api/_mirror-helpers.js';

describe('landing mirror helpers', () => {
  const prev = process.env.BAKLOG_COMP_PRO_EMAILS;

  beforeEach(() => {
    delete process.env.BAKLOG_COMP_PRO_EMAILS;
  });

  afterEach(() => {
    if (prev === undefined) delete process.env.BAKLOG_COMP_PRO_EMAILS;
    else process.env.BAKLOG_COMP_PRO_EMAILS = prev;
  });

  it('extractPlan accepts pro aliases', () => {
    expect(extractPlan({ app_metadata: { plan: 'pro' } })).toBe(true);
    expect(extractPlan({ app_metadata: { plan: 'paid' } })).toBe(true);
    expect(extractPlan({ app_metadata: { plan: 'free' } })).toBe(false);
  });

  it('isProUser grants comp-Pro emails from BAKLOG_COMP_PRO_EMAILS', () => {
    process.env.BAKLOG_COMP_PRO_EMAILS = 'invitee@example.com, other@test.com';
    expect(loadCompProEmails()).toEqual(new Set(['invitee@example.com', 'other@test.com']));
    expect(isCompProEmail('invitee@example.com')).toBe(true);
    expect(
      isProUser({ email: 'invitee@example.com', app_metadata: { plan: 'free' } }),
    ).toBe(true);
    expect(isProUser({ email: 'free@example.com', app_metadata: { plan: 'free' } })).toBe(false);
  });

  it('isValidProfileId rejects traversal and reserved shapes', () => {
    expect(isValidProfileId('default')).toBe(true);
    expect(isValidProfileId('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
    expect(isValidProfileId('../evil')).toBe(false);
    expect(isValidProfileId('')).toBe(false);
    expect(isValidProfileId('bad/id')).toBe(false);
  });

  it('parseMirrorListRows discovers artifacts under multiple profiles', () => {
    const uid = '550e8400-e29b-41d4-a716-446655440000';
    const rows = [
      { name: 'default/games_steam.json', id: '1', updated_at: '2026-01-01T00:00:00Z' },
      { name: `${uid}/games_gog.json`, id: '2', updated_at: '2026-01-02T00:00:00Z' },
      { name: 'default/cache/secrets.bin', id: '3' },
    ];
    const parsed = parseMirrorListRows(rows, uid);
    expect(parsed.profiles.sort()).toEqual(['default', uid].sort());
    expect(
      parsed.artifacts.map((row) => `${row.profile}/${row.path}`).sort(),
    ).toEqual(['default/games_steam.json', `${uid}/games_gog.json`].sort());
    expect(ALLOWED_ARTIFACT.test('games_steam.json')).toBe(true);
  });

  it('resolveArtifactProfile prefers account uuid then default', () => {
    const uid = '550e8400-e29b-41d4-a716-446655440000';
    const artifacts = [
      { path: 'games_steam.json', profile: 'default' },
      { path: 'games_steam.json', profile: uid },
    ];
    expect(resolveArtifactProfile(artifacts, 'games_steam.json', uid)).toBe(uid);
    expect(resolveArtifactProfile([artifacts[0]], 'games_steam.json', uid)).toBe('default');
  });
});
