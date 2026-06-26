/**
 * Consent-gated bug report dialog. Shows the sanitized bundle preview before
 * the tester explicitly sends it. Listens for baklog:open-bug-report so
 * error-boundary.js can open this without importing it.
 */

import { buildBugBundleAsync, copyBugBundleToClipboard, submitBugReport } from './error-boundary.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

let _shellEl = null;
let _dialogEl = null;
let _releaseFocus = null;
let _wired = false;

function ensureShell() {
  if (_shellEl) return;
  const shell = document.createElement('div');
  shell.id = 'bugReportModal';
  shell.className = 'app-modal baklog-bug-report hidden fixed inset-0 z-[60] items-center justify-center p-4 bg-black/70';
  shell.setAttribute('role', 'presentation');
  shell.innerHTML = `
    <div class="baklog-bug-report-card" role="dialog" aria-modal="true" aria-labelledby="bugReportTitle">
      <div class="baklog-bug-report-head">
        <h2 id="bugReportTitle" class="baklog-bug-report-title">Send bug report</h2>
        <button type="button" class="baklog-bug-report-close" data-action="cancel" aria-label="Close">&times;</button>
      </div>
      <div class="baklog-bug-report-body">
        <p class="baklog-bug-report-lead">
          Review what will be sent. Personal notes, library JSON, and credentials are never included.
          Nothing leaves your machine until you click <strong>Send report</strong>.
        </p>
        <label class="baklog-bug-report-label" for="bugReportContact">Contact email (optional)</label>
        <input type="email" id="bugReportContact" class="baklog-bug-report-field" maxlength="320" autocomplete="email" placeholder="you@example.com" />
        <label class="baklog-bug-report-label" for="bugReportNote">What were you doing? (optional)</label>
        <textarea id="bugReportNote" class="baklog-bug-report-field baklog-bug-report-note" maxlength="2000" rows="3" placeholder="Steps to reproduce, what you expected…"></textarea>
        <label class="baklog-bug-report-label" for="bugReportPreview">Payload preview</label>
        <pre id="bugReportPreview" class="baklog-bug-report-preview" aria-readonly="true"></pre>
        <p id="bugReportStatus" class="baklog-bug-report-status hidden" role="status" aria-live="polite"></p>
      </div>
      <div class="baklog-bug-report-foot">
        <button type="button" class="baklog-bug-report-btn baklog-bug-report-btn-neutral" data-action="cancel">Cancel</button>
        <button type="button" class="baklog-bug-report-btn baklog-bug-report-btn-neutral" data-action="copy">Copy instead</button>
        <button type="button" class="baklog-bug-report-btn baklog-bug-report-btn-primary" data-action="send">Send report</button>
      </div>
    </div>
  `;
  document.body.appendChild(shell);
  _shellEl = shell;
  _dialogEl = shell.querySelector('[role="dialog"]');

  shell.addEventListener('click', (ev) => {
    if (ev.target === shell) closeBugReportDialog();
  });
  shell.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'cancel') closeBugReportDialog();
    else if (action === 'copy') copyFromDialog(btn);
    else if (action === 'send') sendFromDialog(btn);
  });
}

function setStatus(text, isError = false) {
  const node = document.getElementById('bugReportStatus');
  if (!node) return;
  if (!text) {
    node.classList.add('hidden');
    node.textContent = '';
    node.classList.remove('baklog-bug-report-status--error');
    return;
  }
  node.textContent = text;
  node.classList.remove('hidden');
  node.classList.toggle('baklog-bug-report-status--error', isError);
}

async function refreshPreview() {
  const preview = document.getElementById('bugReportPreview');
  if (!preview) return;
  preview.textContent = 'Loading preview…';
  const bundle = await buildBugBundleAsync();
  const transport = {
    ...bundle,
    errors: {
      ...bundle.errors,
      persisted: bundle.errors.persisted.slice(-25),
    },
  };
  preview.textContent = JSON.stringify(transport, null, 2);
}

export function openBugReportDialog({ note = '', contact = '' } = {}) {
  if (typeof document === 'undefined' || !document.body) return;
  ensureShell();
  setStatus('');
  refreshPreview();
  const contactEl = document.getElementById('bugReportContact');
  const noteEl = document.getElementById('bugReportNote');
  if (contactEl) contactEl.value = contact || '';
  if (noteEl) noteEl.value = note || '';
  _shellEl.classList.remove('hidden');
  _shellEl.classList.add('flex');
  _releaseFocus?.();
  const releaseTrap = trapFocus(_dialogEl);
  const releaseEsc = bindEscapeClose(_dialogEl, closeBugReportDialog);
  _releaseFocus = () => {
    releaseTrap();
    releaseEsc();
    _releaseFocus = null;
  };
  contactEl?.focus();
}

export function closeBugReportDialog() {
  if (!_shellEl) return;
  _releaseFocus?.();
  _shellEl.classList.add('hidden');
  _shellEl.classList.remove('flex');
  setStatus('');
}

async function copyFromDialog(btn) {
  const ok = await copyBugBundleToClipboard();
  if (btn) {
    const original = btn.dataset.originalLabel || btn.textContent;
    btn.dataset.originalLabel = original;
    btn.textContent = ok ? 'Copied' : 'Copy failed';
    window.setTimeout(() => {
      if (btn.textContent === 'Copied' || btn.textContent === 'Copy failed') {
        btn.textContent = original;
      }
    }, 1400);
  }
  setStatus(ok ? 'Bug bundle copied to clipboard.' : 'Could not copy to clipboard.', !ok);
}

async function sendFromDialog(btn) {
  const contact = document.getElementById('bugReportContact')?.value || '';
  const note = document.getElementById('bugReportNote')?.value || '';
  const original = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Sending…';
  }
  setStatus('Sending report…');
  try {
    await submitBugReport({ contact, note });
    setStatus('Report sent. Thank you!');
    window.setTimeout(() => closeBugReportDialog(), 1200);
  } catch (err) {
    setStatus(err?.message || 'Send failed. Try Copy instead or paste into a GitHub issue.', true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = original || 'Send report';
    }
  }
}

/** Wire the baklog:open-bug-report event once at bootstrap. */
export function initBugReportDialog() {
  if (_wired || typeof window === 'undefined') return;
  _wired = true;
  window.addEventListener('baklog:open-bug-report', () => openBugReportDialog());
}
