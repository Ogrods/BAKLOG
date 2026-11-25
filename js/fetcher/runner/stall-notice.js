/**
 * Cheap stuck-fetcher diagnosis: detect stall watchdog log lines and offer
 * a force-reset CTA (close browser / clear queue). Client soft notice when
 * no progress-shaped output for ~30s (before the 60s server stall line).
 */

const STALL_RE = /\[server\]\s+no output for\s+(\d+)s\s+[—\-].*still running/i;
const FORCE_KILL_RE = /\[server\]\s+no output for\s+(\d+)s\s+[—\-].*force-kill/i;

/**
 * @param {string} text
 * @returns {{ seconds: number, fatal: boolean, soft?: boolean } | null}
 */
export function parseStallLogLine(text) {
  const raw = String(text || '');
  let m = raw.match(FORCE_KILL_RE);
  if (m) return { seconds: Number(m[1]), fatal: true, soft: false };
  m = raw.match(STALL_RE);
  if (m) return { seconds: Number(m[1]), fatal: false, soft: false };
  return null;
}

/**
 * @param {HTMLElement | null | undefined} panel
 * @param {{ seconds: number, fatal: boolean, soft?: boolean } | null} stall
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
  let msg;
  if (stall.soft) {
    msg = `No progress update for ${sec}s - check the log below.`;
  } else if (stall.fatal) {
    msg = `No output for ${sec}s - browser/process force-killed.`;
  } else {
    msg = `No output for ${sec}s - fetcher may be stuck.`;
  }
  el.replaceChildren();
  const span = document.createElement('span');
  span.className = 'fh-log-stall-msg';
  span.textContent = msg;
  el.append(span);
  if (!stall.soft) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'fh-log-btn fh-log-stall-retry';
    btn.setAttribute('data-role', 'stall-retry');
    btn.textContent = 'Close browser and retry';
    btn.title = 'Force-reset the fetcher queue and close a stuck browser session';
    el.append(btn);
  }
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
