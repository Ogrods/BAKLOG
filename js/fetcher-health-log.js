/**
 * Static chrome for the fetcher run-log panel.
 *
 * The log panel's live behaviour (open/close, tail-follow, status sync, cancel)
 * is tightly coupled to the fetcher-runner closure in fetcher-health.js and
 * stays there. This module holds only the *chrome* — the structural markup and
 * the pure presentational helpers — so the runner module carries less inline
 * HTML. fetcher-health.js imports these; its public exports are unchanged.
 */

/** Inner HTML for the log panel shell (header buttons + body + jump pill). */
export const LOG_PANEL_CHROME_HTML = `
      <div class="fh-log-head">
        <div class="fh-log-headings">
          <span class="fh-log-title" data-role="title">Fetcher log</span>
          <span class="fh-log-status" data-role="status" aria-live="polite">idle</span>
        </div>
        <button type="button" class="fh-log-btn fh-log-btn-cancel hidden" data-role="cancel" title="Stop all queued and running fetchers (Shift+click: force reset queue)">Cancel</button>
        <button type="button" class="fh-log-btn" data-role="clear" title="Clear log output (does not stop running fetchers)">Clear</button>
        <button type="button" class="fh-log-btn fh-log-toggle" data-role="close" aria-expanded="true" aria-label="Collapse log panel" title="Collapse log panel"><span class="fh-log-toggle-icon" aria-hidden="true">&#9662;</span></button>
      </div>
      <div class="fh-log-body" data-role="body"></div>
      <button type="button" class="fh-log-jump hidden" data-role="jump" aria-label="Jump to latest line" title="Jump to latest">&darr;</button>
    `;

/** Placeholder shown in an empty log body before any fetcher activity. */
export const LOG_EMPTY_MESSAGE =
  'No fetcher activity yet. Run a fetcher from the chips above to populate.';

/** Accessible label / tooltip for the collapse toggle given its state. */
export function logCollapseLabel(collapsed) {
  return collapsed ? 'Expand log panel' : 'Collapse log panel';
}
