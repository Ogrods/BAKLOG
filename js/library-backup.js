import { baklogFetch } from './api-client.js';
import { isAccountAuthMode, isLocalProfilesEnabled } from './auth-gate.js';
import { LIBRARY_STORE_JSON, WISHLIST_FETCHER_JSON } from './fetcher-registry.js';
import { fetchLibraryJson } from './library-load.js';
import { activeProfileId } from './profiles.js';

/** Catalog filenames mirrored from fetcher-registry.js + itad_prices.json. */
export const LIBRARY_BACKUP_FILENAMES = [
  ...Object.values(LIBRARY_STORE_JSON),
  ...Object.values(WISHLIST_FETCHER_JSON),
  'itad_prices.json',
];

function normalizeLibraryImportPayload(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  if (raw.catalogs && typeof raw.catalogs === 'object' && !Array.isArray(raw.catalogs)) {
    return raw;
  }
  return null;
}

/** Downloadable library backup (games_*.json + itad_prices.json). */
export async function exportLibraryBackupDoc() {
  const catalogs = {};
  await Promise.all(LIBRARY_BACKUP_FILENAMES.map(async (name) => {
    const data = await fetchLibraryJson(name);
    if (data) catalogs[name] = data;
  }));
  return {
    schema_version: 1,
    catalogs,
    exported_at: new Date().toISOString(),
  };
}

/** Restore catalogs via POST /api/catalogs/import, then caller should reloadGames(). */
export async function importLibraryBackupDoc(raw) {
  const incoming = normalizeLibraryImportPayload(raw);
  if (!incoming) throw new Error('invalid library backup');
  const catalogs = incoming.catalogs;
  const names = Object.keys(catalogs);
  if (!names.length) throw new Error('library backup has no catalogs');

  const body = { catalogs };
  if (!isAccountAuthMode() || isLocalProfilesEnabled()) {
    body.profile = activeProfileId();
  }

  const res = await baklogFetch('/api/catalogs/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.error || `library import failed (${res.status})`);
  }
  return res.json();
}
