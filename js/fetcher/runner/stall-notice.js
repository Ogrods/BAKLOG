/**
 * Cheap stuck-fetcher diagnosis: detect stall watchdog log lines and offer
 * a force-reset CTA (close browser / clear queue). No CDP lastUrl plumbing.
 */

const STALL_RE = /\[server\]\s+no output for\s+(\d+)s\s+[—\-].*still running/i;
const FORCE_KILL_RE = /\[server\]\s+no output for\s+(\d+)s\s+[—\-].*force-kill/i;

/**
 * @param {string} text
 * @returns {{ seconds: number, fatal: boolean } | null}
 */
export function parseStallLogLine(text) {
  const raw = String(text || '');
  let m = raw.match(FORCE_KILL_RE);
  if (m) return { seconds: Number(m[1]), fatal: true };
  m = raw.match(STALL_RE);
  if (m) return { seconds: Number(m[1]), fatal: false };
  return null;
}

/**
 * @param {HTMLElement | null | undefined} panel
 * @param {{ seconds: number, fatal: boolean } | null} stall
 */
export function updateStallNotice(panel, stall) {
  if (!panel) return;
  let el = panel.querySelector('[data-role="stall-notice"]');
  if (!stall) {
    if (el) {
      el.classList.add('hidden');
      el.replaceChildren();
    }
    return;
  }
  if (!el) {
    el = document.createElement('div');
    el.className = 'fh-log-stall-notice';
    el.setAttribute('data-role', 'stall-notice');
    el.setAttribute('role', 'status');
    const head = panel.querySelector('.fh-log-head');
    if (head?.nextSibling) panel.insertBefore(el, head.nextSibling);
    else panel.appendChild(el);
  }
  el.classList.remove('hidden');
  const sec = stall.seconds;
  const msg = stall.fatal
    ? `No output for ${sec}s - browser/process force-killed.`
    : `No output for ${sec}s - fetcher may be stuck.`;
  el.replaceChildren();
  const span = document.createElement('span');
  span.className = 'fh-log-stall-msg';
  span.textContent = msg;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'fh-log-btn fh-log-stall-retry';
  btn.setAttribute('data-role', 'stall-retry');
  btn.textContent = 'Close browser and retry';
  btn.title = 'Force-reset the fetcher queue and close a stuck browser session';
  el.append(span, btn);
}

/**
 * @param {HTMLElement | null | undefined} panel
 * @param {() => void | Promise<void>} onRetry
 */
export function wireStallRetryOnce(panel, onRetry) {
  if (!panel || panel.dataset.stallRetryWired === '1') return;
  panel.dataset.stallRetryWired = '1';
  panel.addEventListener('click', (ev) => {
    const btn = ev.target?.closest?.('[data-role="stall-retry"]');
    if (!btn || !panel.contains(btn)) return;
    ev.preventDefault();
    void onRetry();
  });
}
