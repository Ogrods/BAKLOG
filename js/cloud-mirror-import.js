import { baklogFetch } from './api-client.js';

/**
 * Pull mirrored catalogs + personal data from Supabase into the active profile.
 * @param {{ includePersonal?: boolean, paths?: string[] }} [options]
 */
export async function importFromCloudMirror(options = {}) {
  const body = {};
  if (options.includePersonal === false) body.includePersonal = false;
  if (Array.isArray(options.paths) && options.paths.length) body.paths = options.paths;

  const res = await baklogFetch('/api/mirror/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    throw new Error(data.error || `Cloud mirror import failed (${res.status})`);
  }
  return data;
}
