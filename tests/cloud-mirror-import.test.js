/* @vitest-environment node */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const { mockFetch } = vi.hoisted(() => ({
  mockFetch: vi.fn(),
}));

vi.mock('../js/api-client.js', () => ({
  baklogFetch: (...args) => mockFetch(...args),
}));

import { importFromCloudMirror } from '../js/cloud-mirror-import.js';

describe('cloud-mirror-import', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('posts to /api/mirror/import and returns parsed body', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, count: 2, imported: ['games_steam.json', 'data/personal.json'] }),
    });
    const result = await importFromCloudMirror({ includePersonal: true });
    expect(result.count).toBe(2);
    expect(mockFetch).toHaveBeenCalledWith('/api/mirror/import', expect.objectContaining({ method: 'POST' }));
  });

  it('throws server error message on failure', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: 'no importable mirror artifacts' }),
    });
    await expect(importFromCloudMirror()).rejects.toThrow(/no importable mirror artifacts/);
  });
});
