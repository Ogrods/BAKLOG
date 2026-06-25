import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../js/library-load.js', () => ({
  fetchLibraryJson: vi.fn(async (name) => (
    name === 'games_steam.json' ? { games: [{ store: 'steam', id: '1', name: 'Test' }] } : null
  )),
}));

vi.mock('../js/api-client.js', () => ({
  baklogFetch: vi.fn(),
}));

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: () => false,
  isLocalProfilesEnabled: () => false,
}));

vi.mock('../js/profiles.js', () => ({
  activeProfileId: () => 'default',
}));

import { baklogFetch } from '../js/api-client.js';
import {
  LIBRARY_BACKUP_FILENAMES,
  exportLibraryBackupDoc,
  importLibraryBackupDoc,
} from '../js/library-backup.js';

describe('library-backup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists all library and wishlist catalog filenames', () => {
    expect(LIBRARY_BACKUP_FILENAMES).toContain('games_steam.json');
    expect(LIBRARY_BACKUP_FILENAMES).toContain('games_wishlist.json');
    expect(LIBRARY_BACKUP_FILENAMES).toContain('itad_prices.json');
    expect(LIBRARY_BACKUP_FILENAMES.length).toBe(21);
  });

  it('exportLibraryBackupDoc bundles only files that exist', async () => {
    const doc = await exportLibraryBackupDoc();
    expect(doc.schema_version).toBe(1);
    expect(doc.catalogs['games_steam.json'].games[0].name).toBe('Test');
    expect(doc.catalogs['games_gog.json']).toBeUndefined();
    expect(doc.exported_at).toBeTruthy();
  });

  it('importLibraryBackupDoc posts catalogs to the server', async () => {
    baklogFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, imported: ['games_steam.json'], count: 1 }),
    });
    const result = await importLibraryBackupDoc({
      catalogs: { 'games_steam.json': { games: [] } },
    });
    expect(result.count).toBe(1);
    expect(baklogFetch).toHaveBeenCalledWith('/api/catalogs/import', expect.objectContaining({
      method: 'POST',
    }));
  });

  it('rejects invalid backup shape', async () => {
    await expect(importLibraryBackupDoc({ personal: {} })).rejects.toThrow('invalid library backup');
  });
});
