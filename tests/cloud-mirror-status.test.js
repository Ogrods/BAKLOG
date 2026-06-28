import { describe, expect, it } from 'vitest';
import {
  describeImportScope,
  formatMirrorTimestamp,
  listImportableArtifactPaths,
  summarizeLocalUploadState,
} from '../js/cloud-mirror-status.js';

describe('cloud-mirror-status', () => {
  it('summarizeLocalUploadState reports pending when empty', () => {
    const out = summarizeLocalUploadState({ artifacts: {}, last_upload_at: null });
    expect(out.kind).toBe('pending');
    expect(out.line).toMatch(/No uploads yet/);
  });

  it('summarizeLocalUploadState counts ok and error artifacts', () => {
    const out = summarizeLocalUploadState({
      artifacts: {
        'games_steam.json': { status: 'ok', uploaded_at: '2026-06-01T12:00:00Z' },
        'games_gog.json': { status: 'error', uploaded_at: '2026-06-01T12:00:00Z' },
      },
      last_upload_at: '2026-06-01T12:00:00Z',
    });
    expect(out.kind).toBe('error');
    expect(out.line).toMatch(/1 ok, 1 failed/);
  });

  it('listImportableArtifactPaths sorts paths', () => {
    expect(
      listImportableArtifactPaths([
        { path: 'games_gog.json' },
        { path: 'games_steam.json' },
      ]),
    ).toEqual(['games_gog.json', 'games_steam.json']);
  });

  it('describeImportScope groups mirror artifacts', () => {
    const scope = describeImportScope([
      'games_steam.json',
      'games_wishlist_steam.json',
      'data/personal.json',
      'itad_prices.json',
    ]);
    expect(scope).toContain('1 library catalog');
    expect(scope).toContain('1 wishlist catalog');
    expect(scope.some((line) => /personal/.test(line))).toBe(true);
    expect(scope.some((line) => /ITAD/i.test(line))).toBe(true);
  });

  it('formatMirrorTimestamp returns input when invalid', () => {
    expect(formatMirrorTimestamp('not-a-date')).toBe('not-a-date');
  });
});
