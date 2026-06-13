/**
 * BAKLOG Pro purchase splash — dedicated view tab (#pro).
 * Checkout URLs sync with shared/pro_checkout.py + js/pro-checkout.js.
 * Copy sync pair: PRO_PROMO in js/sponsored-deals.js ↔ landing/index.html paid tier.
 */

import { baklogFetch } from './api-client.js';
import {
  getAccountEmail,
  getAccountProfileId,
  isAccountAuthMode,
  isPro,
  proCheckoutUrls,
  refreshAccountPlan,
} from './auth-gate.js';
import { escapeAttr, escapeHtml } from './dom-util.js';
import { PRO_CHECKOUT_MONTHLY, PRO_CHECKOUT_YEARLY, buildProCheckoutUrl } from './pro-checkout.js';
import { PRO_PROMO } from './sponsored-deals.js';
import { switchView } from './filters-ui.js';
import { state } from './state.js';
import { savePrefs } from './prefs.js';

export const PRO_WELCOME_STORAGE_KEY = 'baklog-pro-welcome';

const PRO_BANNER_MONTHLY = 'assets/baklog-pro-polar.png';
const PRO_BANNER_YEARLY = 'assets/baklog-pro-polar-yearly.png';

let proViewWired = false;
let checkoutSuccessPending = false;
let licenseActivating = false;
let selectedProPlan = 'yearly';

/** True while checkout return or license activation is still in flight (before reload). */
export function isProActivationPending() {
  return checkoutSuccessPending || licenseActivating;
}

function clearActivationPending() {
  checkoutSuccessPending = false;
  licenseActivating = false;
}

function completeProActivation({ message = 'Pro is active - reloading…', reloadMs = 500 } = {}) {
  try {
    sessionStorage.setItem(PRO_WELCOME_STORAGE_KEY, '1');
  } catch (_) { /* private mode */ }
  clearActivationPending();
  setProStatus(message, true);
  window.setTimeout(() => location.reload(), reloadMs);
}

function proCheckoutLink(kind) {
  const urls = proCheckoutUrls();
  const fromConfig = kind === 'yearly' ? urls.yearly : urls.monthly;
  const base = fromConfig || (kind === 'yearly' ? PRO_CHECKOUT_YEARLY : PRO_CHECKOUT_MONTHLY);
  if (!isAccountAuthMode()) return base;
  return buildProCheckoutUrl(base, {
    email: getAccountEmail(),
    externalId: getAccountProfileId(),
  });
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
    <p class="pro-view-success-lead">Finish activation below - hosted accounts refresh automatically; local installs paste the license key from your Polar receipt.</p>
  </div>`;
}

function proHeroBannerSrc(plan) {
  return plan === 'yearly' ? PRO_BANNER_YEARLY : PRO_BANNER_MONTHLY;
}

function proHeroBannerHtml(plan) {
  const src = escapeAttr(proHeroBannerSrc(plan));
  return `<img class="pro-view-hero-banner" data-pro-hero-banner src="${src}" alt="BAKLOG Pro" width="1200" height="630" loading="lazy" decoding="async" />`;
}

function proFeaturesListHtml({ compact = false } = {}) {
  return PRO_PROMO.features
    .map((f) => {
      const icon = f.icon ? `<span class="pro-view-perk-icon" aria-hidden="true">${escapeHtml(f.icon)}</span>` : '';
      if (compact) {
        return `<li><strong>${escapeHtml(f.title)}</strong> - ${escapeHtml(f.desc)}</li>`;
      }
      return `<li class="pro-view-perk">
        ${icon}
        <div class="pro-view-perk-body">
          <strong>${escapeHtml(f.title)}</strong>
          <span>${escapeHtml(f.desc)}</span>
        </div>
      </li>`;
    })
    .join('');
}

function proCompareHtml() {
  const head = `<thead><tr>
    <th scope="col"></th>
    <th scope="col">Free</th>
    <th scope="col">Pro</th>
  </tr></thead>`;
  const rows = PRO_PROMO.tierCompare
    .map((row) => `<tr>
      <th scope="row">${escapeHtml(row.feature)}</th>
      <td>${escapeHtml(row.free)}</td>
      <td>${escapeHtml(row.pro)}</td>
    </tr>`)
    .join('');
  return `<div class="pro-view-compare-wrap">
    <h3 class="pro-view-section-title">What stays free vs what Pro adds</h3>
    <p class="pro-view-compare-lead">Import, browse, and pick what to play stay free. Pro adds bulk refresh, background sync, and no sponsored cards.</p>
    <table class="pro-view-compare" aria-label="Free vs Pro">${head}<tbody>${rows}</tbody></table>
  </div>`;
}

function proTrustHtml() {
  const items = PRO_PROMO.trustPoints
    .map((point) => `<li>${escapeHtml(point)}</li>`)
    .join('');
  return `<div class="pro-view-trust" role="note" aria-label="Trust and privacy">
    <ul class="pro-view-trust-list">${items}</ul>
  </div>`;
}

function proPricingHtml() {
  const monthly = escapeAttr(proCheckoutLink('monthly'));
  const yearly = escapeAttr(proCheckoutLink('yearly'));
  const monthlyPressed = selectedProPlan === 'monthly' ? 'true' : 'false';
  const yearlyPressed = selectedProPlan === 'yearly' ? 'true' : 'false';
  const checkoutHref = selectedProPlan === 'yearly' ? yearly : monthly;
  const checkoutLabel = selectedProPlan === 'yearly' ? PRO_PROMO.ctaYearly : PRO_PROMO.cta;

  return `<div class="pro-view-pricing">
    <div class="pro-view-toggle" role="group" aria-label="Billing interval">
      <button type="button" class="pro-view-toggle-btn${selectedProPlan === 'monthly' ? ' is-active' : ''}" data-pro-plan="monthly" aria-pressed="${monthlyPressed}">Monthly · $5/mo</button>
      <button type="button" class="pro-view-toggle-btn${selectedProPlan === 'yearly' ? ' is-active' : ''}" data-pro-plan="yearly" aria-pressed="${yearlyPressed}">Yearly · $50/yr <span class="pro-view-save">Save $10</span></button>
    </div>
    <a class="pro-view-btn pro-view-btn--primary" data-pro-checkout href="${checkoutHref}" target="_blank" rel="noopener noreferrer">${escapeHtml(checkoutLabel)}</a>
    <p class="pro-view-founder">${escapeHtml(PRO_PROMO.founderNote)}</p>
  </div>`;
}

function proActivationHtml() {
  if (isAccountAuthMode()) {
    const email = getAccountEmail();
    const emailNote = email
      ? `Checkout with <strong>${escapeHtml(email)}</strong> so Pro links to this account.`
      : 'Use the same email as your BAKLOG account at checkout.';
    return `
      <div class="pro-view-activate">
        <h3 class="pro-view-section-title">After checkout</h3>
        <p class="pro-view-note">${emailNote} After payment, click refresh - or sign out and back in.</p>
        <div class="pro-view-actions">
          <button type="button" class="pro-view-btn pro-view-btn--ghost" data-pro-refresh>Refresh Pro status</button>
        </div>
      </div>`;
  }
  return `
    <div class="pro-view-activate">
      <h3 class="pro-view-section-title">After checkout</h3>
      <p class="pro-view-note">Subscribe above, then paste the <code>BAKLOG-XXXX</code> license key from your Polar receipt.</p>
      <form class="pro-view-license" data-pro-license-form>
        <label class="pro-view-license-label" for="proViewLicenseKey">License key</label>
        <div class="pro-view-license-row">
          <input id="proViewLicenseKey" class="pro-view-license-input" type="text" name="license_key" placeholder="BAKLOG-XXXX-XXXX" autocomplete="off" spellcheck="false" />
          <button type="submit" class="pro-view-btn">Activate</button>
        </div>
      </form>
      <div class="pro-view-actions">
        <button type="button" class="pro-view-btn pro-view-btn--ghost" data-pro-refresh>Refresh Pro status</button>
      </div>
    </div>`;
}

function proActiveHtml() {
  return `<div class="pro-view-card pro-view-card--active" role="region" aria-label="BAKLOG Pro">
    <p class="pro-view-eyebrow">${escapeHtml(PRO_PROMO.label)}</p>
    <h2 class="pro-view-title">You&apos;re on Pro</h2>
    <p class="pro-view-lead">Sponsored deal slots are off. Perks roll out on the same open codebase - more conveniences land over time.</p>
    <ul class="pro-view-features">${proFeaturesListHtml({ compact: true })}</ul>
  </div>`;
}

function proPitchHtml({ showSuccess = false } = {}) {
  const planClass = selectedProPlan === 'yearly' ? 'pro-view-funnel--yearly' : 'pro-view-funnel--monthly';
  return `${showSuccess ? successBannerHtml() : ''}
    <div class="pro-view-funnel ${planClass}" role="region" aria-label="BAKLOG Pro">
      <header class="pro-view-hero">
        ${proHeroBannerHtml(selectedProPlan)}
        <div class="pro-view-hero-main">
          <div class="pro-view-hero-copy">
            <h1 class="pro-view-headline">${escapeHtml(PRO_PROMO.title)}</h1>
            <p class="pro-view-subhead">${escapeHtml(PRO_PROMO.tagline)}</p>
          </div>
          ${proPricingHtml()}
        </div>
      </header>
      <section class="pro-view-perks" aria-label="Pro features">
        <h3 class="pro-view-section-title">Everything in Pro</h3>
        <ul class="pro-view-perk-grid">${proFeaturesListHtml()}</ul>
      </section>
      ${proCompareHtml()}
      ${proTrustHtml()}
      ${proActivationHtml()}
      <p id="proViewStatus" class="pro-view-status" hidden></p>
    </div>`;
}

function applyProPlanToggle(root, plan) {
  selectedProPlan = plan === 'yearly' ? 'yearly' : 'monthly';
  const monthly = proCheckoutLink('monthly');
  const yearly = proCheckoutLink('yearly');
  root.querySelectorAll('[data-pro-plan]').forEach((btn) => {
    const active = btn.dataset.proPlan === selectedProPlan;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  const checkout = root.querySelector('[data-pro-checkout]');
  if (checkout) {
    checkout.href = selectedProPlan === 'yearly' ? yearly : monthly;
    checkout.textContent = selectedProPlan === 'yearly' ? PRO_PROMO.ctaYearly : PRO_PROMO.cta;
  }
  const banner = root.querySelector('[data-pro-hero-banner]');
  if (banner) banner.src = proHeroBannerSrc(selectedProPlan);
  const funnel = root.querySelector('.pro-view-funnel');
  if (funnel) {
    funnel.classList.toggle('pro-view-funnel--yearly', selectedProPlan === 'yearly');
    funnel.classList.toggle('pro-view-funnel--monthly', selectedProPlan === 'monthly');
  }
}

export function renderProView({ showSuccess = false } = {}) {
  const el = document.getElementById('proViewRoot');
  if (!el) return;
  if (isPro()) {
    el.innerHTML = proActiveHtml();
    return;
  }
  el.innerHTML = proPitchHtml({ showSuccess: showSuccess || checkoutSuccessPending });
  applyProPlanToggle(el, selectedProPlan);
}

export function applyProTabVisibility() {
  const tab = document.querySelector('.view-tab[data-view="pro"]');
  if (!tab) return;
  const pending = isProActivationPending();
  const show = !isPro() || pending;
  tab.classList.toggle('hidden', !show);
  if (!show && !pending && state.activeView === 'pro') {
    switchView('dashboard');
    state.prefs.activeView = 'dashboard';
    savePrefs();
  }
}

export function goToProView() {
  if (isPro() && !isProActivationPending()) return;
  switchView('pro');
}

/** One-time post-reload confirmation after Pro activation (sessionStorage flag). */
export function showProWelcomeBanner() {
  let flagged = false;
  try {
    flagged = sessionStorage.getItem(PRO_WELCOME_STORAGE_KEY) === '1';
  } catch (_) { /* private mode */ }
  if (!flagged || !isPro()) return;
  const host = document.getElementById('proWelcomeBanner');
  if (!host) return;
  try {
    sessionStorage.removeItem(PRO_WELCOME_STORAGE_KEY);
  } catch (_) { /* private mode */ }
  host.innerHTML = `<div class="migration-banner-body">
      <div>
        <strong>You&apos;re on Pro.</strong>
        Sponsored deal slots are off. Perks apply on this machine.
      </div>
      <div class="migration-banner-actions">
        <button type="button" class="pro-welcome-dismiss bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded text-sm">Dismiss</button>
      </div>
    </div>`;
  host.classList.remove('hidden');
  host.querySelector('.pro-welcome-dismiss')?.addEventListener('click', () => {
    host.classList.add('hidden');
    host.innerHTML = '';
  });
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
  licenseActivating = true;
  setProStatus('Validating with Polar…', true);
  try {
    const res = await baklogFetch('/api/license/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      licenseActivating = false;
      setProStatus(data.message || data.error || 'Activation failed.', false);
      return;
    }
    completeProActivation({
      message: data.message || 'BAKLOG Pro activated - reloading…',
      reloadMs: 600,
    });
  } catch {
    licenseActivating = false;
    setProStatus('Could not reach the local server.', false);
  } finally {
    if (btn && !licenseActivating) btn.disabled = false;
  }
}

export async function handleCheckoutSuccessReturn() {
  if (!checkoutSuccessPending) return;
  renderProView({ showSuccess: true });
  if (isAccountAuthMode()) {
    setProStatus('Checking your account…', true);
    const plan = await refreshAccountPlan();
    if (plan === 'pro') {
      completeProActivation();
      return;
    }
    setProStatus('Payment received. Pro may take a moment - click Refresh Pro status, or paste your license key below.', false);
    return;
  }
  setProStatus('Paste the license key from your Polar receipt email to finish activation.', true);
  document.getElementById('proViewLicenseKey')?.focus();
}

// Connections-tab Pro card pitch. Intentionally distinct from the dashboard
// banner (PRO_PROMO.title) and the house upsells so each surface reads fresh;
// leans on the automation angle that fits the Connections (fetcher) context.
const CONN_PRO_PITCH = 'Set every store to refresh on its own, even when BAKLOG is closed';

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
    <p class="conn-pro-title">${escapeHtml(PRO_PROMO.label)}</p>
    <p class="conn-pro-lead">${escapeHtml(CONN_PRO_PITCH)} - ${escapeHtml(PRO_PROMO.price)}.</p>
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
    const planBtn = ev.target.closest('[data-pro-plan]');
    if (planBtn) {
      ev.preventDefault();
      applyProPlanToggle(document.getElementById('proViewRoot'), planBtn.dataset.proPlan);
      return;
    }
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
      completeProActivation({ reloadMs: 400 });
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
