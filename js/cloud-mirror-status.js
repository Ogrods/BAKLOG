import { baklogFetch } from './api-client.js';

/**
 * @typedef {{ path?: string, profile?: string, updated_at?: string }} MirrorArtifactRow
 * @typedef {{ artifacts?: Record<string, { status?: string, uploaded_at?: string }>, last_upload_at?: string | null }} LocalUploadState
 */

/** @returns {Promise<{ artifacts: MirrorArtifactRow[], localUploadState: LocalUploadState }>} */
export async function fetchMirrorSnapshot() {
  const res = await baklogFetch('/api/mirror');
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    throw new Error(data.error || `Mirror read failed (${res.status})`);
  }
  return {
    artifacts: Array.isArray(data.artifacts) ? data.artifacts : [],
    localUploadState:
      data.localUploadState && typeof data.localUploadState === 'object'
        ? data.localUploadState
        : { artifacts: {}, last_upload_at: null },
  };
}

/**
 * @param {LocalUploadState | null | undefined} localUploadState
 * @returns {{ line: string, kind: 'idle' | 'pending' | 'ok' | 'error' }}
 */
export function summarizeLocalUploadState(localUploadState) {
  const artifacts = localUploadState?.artifacts;
  const entries =
    artifacts && typeof artifacts === 'object' ? Object.entries(artifacts) : [];
  if (!entries.length) {
    return {
      line: 'No uploads yet — refresh a store or save your library (~30s debounce).',
      kind: 'pending',
    };
  }
  const ok = entries.filter(([, row]) => row?.status === 'ok').length;
  const err = entries.filter(([, row]) => row?.status === 'error').length;
  const last = String(localUploadState?.last_upload_at || '').trim();
  const lastBit = last ? ` Last upload ${formatMirrorTimestamp(last)}.` : '';
  if (err > 0) {
    return {
      line: `Mirror upload: ${ok} ok, ${err} failed.${lastBit}`,
      kind: 'error',
    };
  }
  return {
    line: `Mirror upload: ${ok} file${ok === 1 ? '' : 's'} synced.${lastBit}`,
    kind: 'ok',
  };
}

/** @param {MirrorArtifactRow[]} artifacts */
export function listImportableArtifactPaths(artifacts) {
  return (artifacts || [])
    .map((row) => String(row?.path || '').trim())
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
}

/**
 * @param {string[]} paths
 * @returns {string[]}
 */
export function describeImportScope(paths) {
  const lines = [];
  const catalogs = paths.filter((p) => /^games_/.test(p));
  const wishlists = catalogs.filter((p) => p.startsWith('games_wishlist_'));
  const libraries = catalogs.filter((p) => !p.startsWith('games_wishlist_'));
  if (libraries.length) lines.push(`${libraries.length} library catalog${libraries.length === 1 ? '' : 's'}`);
  if (wishlists.length) lines.push(`${wishlists.length} wishlist catalog${wishlists.length === 1 ? '' : 's'}`);
  if (paths.includes('data/personal.json')) lines.push('personal statuses and notes');
  if (paths.includes('itad_prices.json')) lines.push('deal prices (ITAD)');
  if (paths.includes('free_claims.json')) lines.push('claimables feed');
  return lines;
}

/**
 * @param {string} iso
 */
export function formatMirrorTimestamp(iso) {
  const raw = String(iso || '').trim();
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
