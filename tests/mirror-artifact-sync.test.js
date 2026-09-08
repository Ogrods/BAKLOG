import { describe, expect, it } from 'vitest';
import { ALLOWED_ARTIFACT_RE_SOURCE, isAllowedMirrorArtifact } from '../js/mirror-artifacts.js';
import {
  describeImportScope,
  formatLastUploadedBy,
  listImportableArtifactPaths,
  summarizeLocalUploadState,
} from '../js/cloud-mirror-status.js';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('mirror artifact allowlist', () => {
  it('matches Python / landing source strings', () => {
    const py = readFileSync(resolve('shared/mirror_artifacts.py'), 'utf8');
    const m = py.match(/ALLOWED_ARTIFACT_RE_SOURCE\s*=\s*\(\s*\n?\s*r"([^"]+)"/);
    expect(m?.[1]).toBe(ALLOWED_ARTIFACT_RE_SOURCE);

    const landing = readFileSync(resolve('landing/api/_mirror-helpers.js'), 'utf8');
    const lm = landing.match(/ALLOWED_ARTIFACT_RE_SOURCE\s*=\s*\n?\s*"([^"]+)"/);
    // File source uses JS string escapes (\\.); decode before compare.
    expect(lm?.[1]?.replace(/\\\\/g, '\\')).toBe(ALLOWED_ARTIFACT_RE_SOURCE);
  });

  it('accepts catalogs and personal, rejects free_claims', () => {
    expect(isAllowedMirrorArtifact('games_steam.json')).toBe(true);
    expect(isAllowedMirrorArtifact('data/personal.json')).toBe(true);
    expect(isAllowedMirrorArtifact('free_claims.json')).toBe(false);
  });
});

describe('cloud-mirror-status helpers', () => {
  it('summarizes empty and ok states', () => {
    expect(summarizeLocalUploadState(null).kind).toBe('pending');
    expect(
      summarizeLocalUploadState({
        artifacts: { 'games_steam.json': { status: 'ok', uploaded_at: '2026-01-01T00:00:00Z' } },
        last_upload_at: '2026-01-01T00:00:00Z',
      }).kind,
    ).toBe('ok');
  });

  it('describes import scope without free_claims', () => {
    const lines = describeImportScope([
      'games_steam.json',
      'games_wishlist_steam.json',
      'data/personal.json',
      'free_claims.json',
    ]);
    expect(lines.some((l) => /claimable/i.test(l))).toBe(false);
    expect(lines.length).toBeGreaterThan(0);
  });

  it('lists importable paths and last-uploaded-by', () => {
    expect(listImportableArtifactPaths([{ path: 'b.json' }, { path: 'a.json' }])).toEqual([
      'a.json',
      'b.json',
    ]);
    expect(
      formatLastUploadedBy({
        device_id: 'Windows:pc',
        last_upload_at: '2026-01-01T12:00:00Z',
      }),
    ).toMatch(/Last uploaded by Windows:pc/);
  });
});
