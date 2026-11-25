/**
 * Parse fetcher stdout into a short "work done" summary for running chrome.
 * Matches fetchers/_progress.py progress_line / elapsed_progress_line shapes.
 */

/** Countable: `[3/10] (30%) phase: detail` or `[3/10] (30%) phase` */
const PROGRESS_RE =
  /^\s*(?:·\s*)?\[(\d+)\/(\d+)\](?:\s+\((\d+)%\))?\s+(.+?)(?:\s+-\s+still running \(\d+s\))?$/i;

/** Elapsed without counts: `phase - still running (90s)` or `· phase - still running (90s)` */
const ELAPSED_RE =
  /^\s*(?:·\s*)?(.+?)\s+-\s+still running \((\d+)s\)\s*$/i;

/** Starting pulse: `phase - starting` */
const STARTING_RE = /^\s*(?:·\s*)?(.+?)\s+-\s+starting\s*$/i;

/**
 * @param {string} text
 * @returns {string | null} Short summary for status badge / chip title
 */
export function parseProgressSummary(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  // Strip leading arrow phase marker from phase() lines when they carry counts later.
  const line = raw.replace(/^[→·]\s*/, '').trim();

  let m = line.match(PROGRESS_RE);
  if (m) {
    const done = m[1];
    const total = m[2];
    const pctPart = m[3] ? ` (${m[3]}%)` : '';
    let rest = (m[4] || '').trim();
    // Drop trailing still-running clause if nested oddly.
    rest = rest.replace(/\s+-\s+still running \(\d+s\)$/i, '').trim();
    // Prefer "phase" over long "phase: detail" for the badge.
    const phaseOnly = rest.split(':')[0].trim() || rest;
    const detail = rest.includes(':') ? rest.slice(rest.indexOf(':') + 1).trim() : '';
    const detailBit = detail ? `: ${detail.slice(0, 28)}` : '';
    return `[${done}/${total}]${pctPart} ${phaseOnly}${detailBit}`.trim();
  }

  m = line.match(ELAPSED_RE);
  if (m) {
    const phase = (m[1] || '').trim();
    const sec = m[2];
    if (!phase) return null;
    return `${phase} (${sec}s)`;
  }

  m = line.match(STARTING_RE);
  if (m) {
    const phase = (m[1] || '').trim();
    return phase ? `${phase} - starting` : null;
  }

  return null;
}

/** Soft client stall: no progress-shaped line for this long while running. */
export const SOFT_STALL_NO_PROGRESS_MS = 30_000;
