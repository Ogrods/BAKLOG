/**
 * BAKLOG Pro purchase splash — dedicated view tab (#pro).
 * Checkout URLs sync with shared/pro_checkout.py + js/pro-checkout.js.
 */

import { baklogFetch } from './api-client.js';
import {
  getAccountEmail,
  isAccountAuthMode,
  isPro,
  licenseActivationEnabled,
  proCheckoutUrls,
  refreshAccountPlan,
} from './auth-gate.js';
import { escapeAttr, escapeHtml } from './dom-util.js';
import { PRO_CHECKOUT_MONTHLY, PRO_CHECKOUT_YEARLY } from './pro-checkout.js';
import { PRO_PROMO, isProPromoSponsorId } from './sponsored-deals.js';
import { switchView } from './filters-ui.js';
import { state } from './state.js';
import { savePrefs } from './prefs.js';

export { isProPromoSponsorId };

let proViewWired = false;
let checkoutSuccessPending = false;

function proCheckoutLink(kind) {
  const urls = proCheckoutUrls();
  const fromConfig = kind === 'yearly' ? urls.yearly : urls.monthly;
  return fromConfig || (kind === 'yearly' ? PRO_CHECKOUT_YEARLY : PRO_CHECKOUT_MONTHLY);
}

function setProStatus(message, ok) {
  const el = document.getElementById('proViewStatus');
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.textContent = '';
    el.classList.remove('pro-view-status--ok', 'pro-view-status--err');
    return;
  }
  el.hidden = false;
  el.textContent = message;
  el.classList.toggle('pro-view-status--ok', !!ok);
  el.classList.toggle('pro-view-status--err', !ok);
}

function successBannerHtml() {
  return `<div class="pro-view-success" role="status">
    <p class="pro-view-success-title">Payment received</p>
    <p class="pro-view-success-lead">Finish activation below — hosted accounts refresh automatically; local installs paste the license key from your Polar receipt.</p>
  </div>`;
}

function proActiveHtml() {
  return `<div class="pro-view-card pro-view-card--active" role="region" aria-label="BAKLOG Pro">
    <p class="pro-view-eyebrow">BAKLOG Pro</p>
    <h2 class="pro-view-title">You&apos;re on Pro</h2>
    <p class="pro-view-lead">Sponsored deal slots are off. Perks roll out on the same open codebase — more conveniences land over time.</p>
    <ul class="pro-view-features">${PRO_PROMO.features.map(f => `<li><strong>${escapeHtml(f.title)}</strong> — ${escapeHtml(f.desc)}</li>`).join('')}</ul>
  </div>`;
}

function proPitchHtml({ showSuccess = false } = {}) {
  const monthly = escapeAttr(proCheckoutLink('monthly'));
  const yearly = escapeAttr(proCheckoutLink('yearly'));
  const features = PRO_PROMO.features
    .map(f => `<li><strong>${escapeHtml(f.title)}</strong><span>${escapeHtml(f.desc)}</span></li>`)
    .join('');

  let activationBlock = '';
  if (isAccountAuthMode()) {
    const email = getAccountEmail();
    const emailNote = email
      ? `Checkout with <strong>${escapeHtml(email)}</strong> so Pro links to this account.`
      : 'Use the same email as your BAKLOG account at checkout.';
    activationBlock = `
      <p class="pro-view-note">${emailNote} After payment, click refresh — or sign out and back in.</p>
      <div class="pro-view-actions">
        <a class="pro-view-btn" href="${monthly}" target="_blank" rel="noopener noreferrer">Get Pro — $5/mo</a>
        <a class="pro-view-btn pro-view-btn--ghost" href="${yearly}" target="_blank" rel="noopener noreferrer">$50/yr (save $10)</a>
        <button type="button" class="pro-view-btn pro-view-btn--ghost" data-pro-refresh>Refresh Pro status</button>
      </div>`;
  } else if (licenseActivationEnabled()) {
    activationBlock = `
      <p class="pro-view-note">Subscribe, then paste the <code>BAKLOG-XXXX</code> license key from your Polar receipt. Validation runs against Polar from this machine only.</p>
      <div class="pro-view-actions">
        <a class="pro-view-btn" href="${monthly}" target="_blank" rel="noopener noreferrer">Get Pro — $5/mo</a>
        <a class="pro-view-btn pro-view-btn--ghost" href="${yearly}" target="_blank" rel="noopener noreferrer">$50/yr (save $10)</a>
      </div>
      <form class="pro-view-license" data-pro-license-form>
        <label class="pro-view-license-label" for="proViewLicenseKey">License key</label>
        <div class="pro-view-license-row">
          <input id="proViewLicenseKey" class="pro-view-license-input" type="text" name="license_key" placeholder="BAKLOG-XXXX-XXXX" autocomplete="off" spellcheck="false" />
          <button type="submit" class="pro-view-btn">Activate</button>
        </div>
      </form>`;
  } else {
    activationBlock = `
      <p class="pro-view-note">Subscribe on Polar, then paste your license key here. Set <code>BAKLOG_POLAR_ORG_ID</code> on the server to enable activation.</p>
      <div class="pro-view-actions">
        <a class="pro-view-btn" href="${monthly}" target="_blank" rel="noopener noreferrer">Get Pro — $5/mo</a>
        <a class="pro-view-btn pro-view-btn--ghost" href="${yearly}" target="_blank" rel="noopener noreferrer">$50/yr (save $10)</a>
      </div>`;
  }

  return `${showSuccess ? successBannerHtml() : ''}
    <div class="pro-view-card" role="region" aria-label="BAKLOG Pro">
      <p class="pro-view-eyebrow">${escapeHtml(PRO_PROMO.label)}</p>
      <h2 class="pro-view-title">${escapeHtml(PRO_PROMO.title)}</h2>
      <p class="pro-view-price">${escapeHtml(PRO_PROMO.price)}</p>
      <p class="pro-view-lead">${escapeHtml(PRO_PROMO.tagline)}</p>
      <ul class="pro-view-features">${features}</ul>
      ${activationBlock}
      <p id="proViewStatus" class="pro-view-status" hidden></p>
    </div>`;
}

export function renderProView({ showSuccess = false } = {}) {
  const el = document.getElementById('proViewRoot');
  if (!el) return;
  if (isPro()) {
    el.innerHTML = proActiveHtml();
    return;
  }
  el.innerHTML = proPitchHtml({ showSuccess: showSuccess || checkoutSuccessPending });
}

export function applyProTabVisibility() {
  const tab = document.querySelector('.view-tab[data-view="pro"]');
  if (!tab) return;
  const show = !isPro();
  tab.classList.toggle('hidden', !show);
  if (!show && state.activeView === 'pro') {
    switchView('dashboard');
    state.prefs.activeView = 'dashboard';
    savePrefs();
  }
}

export function goToProView() {
  if (isPro()) return;
  switchView('pro');
}

export function markCheckoutSuccessPending() {
  checkoutSuccessPending = true;
}

export function consumeCheckoutQuery() {
  try {
    const params = new URLSearchParams(location.search);
    if (params.get('checkout') !== 'success') return false;
    const u = new URL(location.href);
    u.searchParams.delete('checkout');
    u.searchParams.delete('checkout_id');
    history.replaceState({}, '', u.pathname + u.search + u.hash);
    checkoutSuccessPending = true;
    state.prefs.activeView = 'pro';
    state.activeView = 'pro';
    return true;
  } catch {
    return false;
  }
}

export function consumeProHash() {
  if (location.hash !== '#pro' || isPro()) return false;
  state.prefs.activeView = 'pro';
  state.activeView = 'pro';
  return true;
}

async function submitProLicense(form) {
  const input = form.querySelector('#proViewLicenseKey') || form.querySelector('input[name="license_key"]');
  const key = input?.value?.trim();
  if (!key) {
    setProStatus('Enter your license key.', false);
    return;
  }
  const btn = form.querySelector('button[type="submit"]');
  if (btn) btn.disabled = true;
  setProStatus('Validating with Polar…', true);
  try {
    const res = await baklogFetch('/api/license/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      setProStatus(data.message || data.error || 'Activation failed.', false);
      return;
    }
    setProStatus(data.message || 'BAKLOG Pro activated.', true);
    window.setTimeout(() => location.reload(), 600);
  } catch {
    setProStatus('Could not reach the local server.', false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export async function handleCheckoutSuccessReturn() {
  if (!checkoutSuccessPending) return;
  renderProView({ showSuccess: true });
  if (isAccountAuthMode()) {
    setProStatus('Checking your account…', true);
    const plan = await refreshAccountPlan();
    if (plan === 'pro') {
      checkoutSuccessPending = false;
      setProStatus('Pro is active — reloading…', true);
      window.setTimeout(() => location.reload(), 500);
      return;
    }
    setProStatus('Payment received. Pro may take a moment — click Refresh Pro status, or paste your license key below.', false);
    return;
  }
  setProStatus('Paste the license key from your Polar receipt email to finish activation.', true);
  document.getElementById('proViewLicenseKey')?.focus();
}

export function renderConnectionsProLink() {
  const el = document.getElementById('connProPanel');
  if (!el) return;
  if (isPro()) {
    el.innerHTML = '';
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.innerHTML = `<div class="conn-pro-card conn-pro-card--link" role="region" aria-label="BAKLOG Pro">
    <p class="conn-pro-title">BAKLOG Pro</p>
    <p class="conn-pro-lead">Power-user conveniences — bulk refresh, cloud sync, no sponsored cards. $5/mo or $50/yr.</p>
    <button type="button" class="conn-pro-btn" data-goto-pro-view>View plans &amp; activate</button>
  </div>`;
}

export function wireProView() {
  if (proViewWired) return;
  proViewWired = true;
  const root = document.getElementById('proContainer');
  if (!root) return;
  root.addEventListener('submit', (ev) => {
    const form = ev.target.closest('[data-pro-license-form]');
    if (!form) return;
    ev.preventDefault();
    submitProLicense(form);
  });
  root.addEventListener('click', async (ev) => {
    if (ev.target.closest('[data-goto-pro-view]')) {
      ev.preventDefault();
      goToProView();
      return;
    }
    const btn = ev.target.closest('[data-pro-refresh]');
    if (!btn) return;
    btn.disabled = true;
    setProStatus('Checking your account…', true);
    const plan = await refreshAccountPlan();
    if (plan === 'pro') {
      setProStatus('Pro is active — reloading…', true);
      window.setTimeout(() => location.reload(), 400);
      return;
    }
    setProStatus('Not Pro yet. Finish checkout with your account email, then try again.', false);
    btn.disabled = false;
  });
  document.getElementById('connectionsContainer')?.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-goto-pro-view]')) {
      ev.preventDefault();
      goToProView();
    }
  });
}
