/**
 * Single allowlist for Pro cloud-mirror artifacts.
 * Keep ALLOWED_ARTIFACT_RE_SOURCE in sync with shared/mirror_artifacts.py (AGENTS.md rule 6).
 * free_claims.json is intentionally excluded (public feed, not per-user).
 */

/** @type {string} */
export const ALLOWED_ARTIFACT_RE_SOURCE =
  '^(games_[a-z0-9_]+\\.json|itad_prices\\.json|data/personal\\.json)$';

export const ALLOWED_ARTIFACT = new RegExp(ALLOWED_ARTIFACT_RE_SOURCE);

/**
 * @param {string} relPosix
 * @returns {boolean}
 */
export function isAllowedMirrorArtifact(relPosix) {
  const rel = String(relPosix || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '');
  if (!rel || rel.includes('..')) return false;
  if (rel.toLowerCase().startsWith('cache/') || rel.toLowerCase().includes('/cache/')) {
    return false;
  }
  return ALLOWED_ARTIFACT.test(rel);
}
