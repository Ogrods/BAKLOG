/**
 * Account-type matrix for BAKLOG Pro: beta tester (comp with end date), paying
 * subscriber, permanent comp, dev server, and free. Two layers:
 *   1. Pro tab rendering through the real auth-gate module (config + session data).
 *   2. Entitlement lifecycle: Polar webhook transitions + the daily comp-expire cron.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  applyPaidEntitlement,
  compExpired,
  expireCompMeta,
} from '../web/api/_polar-pending.js';

vi.mock('../js/vendor/supabase-js.mjs', () => ({ createClient: vi.fn() }));
vi.mock('../js/filters-ui.js', () => ({ switchView: vi.fn() }));
vi.mock('../js/prefs.js', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, savePrefs: vi.fn() };
});

const PORTAL = 'https://polar.sh/baklog/portal';
const CHECKOUT = { monthly: 'https://buy.polar.sh/m', yearly: 'https://buy.polar.sh/y' };

/** Server responses (GET /api/config + /api/auth/session) per account type. */
const ACCOUNTS = {
  free: { plan: 'free', admin: false, session: { compUntil: '', paid: false } },
  beta: { plan: 'pro', admin: false, session: { compUntil: '2027-03-31', paid: false } },
  paid: { plan: 'pro', admin: false, session: { compUntil: '', paid: true } },
  permanent: { plan: 'pro', admin: false, session: { compUntil: '', paid: false } },
  dev: { plan: 'pro', admin: true, session: { compUntil: '', paid: false } },
};

async function renderAccount(type) {
  vi.resetModules();
  document.body.innerHTML = `
    <button type="button" class="view-tab hidden" data-view="pro" hidden></button>
    <div id="proContainer"><div id="proViewRoot"></div></div>`;
  const account = ACCOUNTS[type];
  const authGate = await import('../js/auth-gate.js');
  authGate.__applyConfigEntitlementForTest({
    authRequired: true,
    plan: account.plan,
    admin: account.admin,
    proCheckoutEnabled: true,
    proCheckout: CHECKOUT,
    proPortalUrl: PORTAL,
  });
  authGate.__setPlanDetailsForTest(account.session);
  const view = await import('../js/pro-view.js');
  view.applyProTabVisibility();
  view.renderProView();
  return {
    root: document.getElementById('proViewRoot'),
    tab: document.querySelector('.view-tab[data-view="pro"]'),
  };
}

const text = (el) => el.textContent.replace(/\s+/g, ' ');
const hasManage = (root) => [...root.querySelectorAll('a')].some((a) => a.textContent === 'Manage subscription');

describe('Pro tab by account type (real auth-gate)', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it.each(Object.keys(ACCOUNTS))('%s: Pro tab is visible', async (type) => {
    const { tab } = await renderAccount(type);
    expect(tab.hidden).toBe(false);
    expect(tab.classList.contains('hidden')).toBe(false);
  });

  it('free: sales pitch with checkout, no plan card', async () => {
    const { root } = await renderAccount('free');
    expect(root.querySelector('.pro-view-funnel')).toBeTruthy();
    expect(root.querySelector('[data-pro-checkout]')).toBeTruthy();
    expect(root.querySelector('.pro-view-card--active')).toBeNull();
    expect(root.querySelector('.pro-view-card--dev')).toBeNull();
  });

  it('beta tester: end date, optional early support, no manage link', async () => {
    const { root } = await renderAccount('beta');
    const card = root.querySelector('.pro-view-card--active');
    expect(text(card)).toContain('Free beta Pro through Mar 31, 2027.');
    expect(text(card)).toContain('free days you have left are added after your subscription ends');
    expect(card.querySelector('[data-pro-checkout]')?.getAttribute('href')).toContain('buy.polar.sh');
    expect(hasManage(root)).toBe(false);
  });

  it('paying subscriber: subscription active with Polar portal link, no checkout', async () => {
    const { root } = await renderAccount('paid');
    const card = root.querySelector('.pro-view-card--active');
    expect(text(card)).toContain('Pro subscription active.');
    const link = [...card.querySelectorAll('a')].find((a) => a.textContent === 'Manage subscription');
    expect(link?.getAttribute('href')).toBe(PORTAL);
    expect(root.querySelector('[data-pro-checkout]')).toBeNull();
  });

  it('permanent comp: no end date, no checkout, no manage link', async () => {
    const { root } = await renderAccount('permanent');
    const card = root.querySelector('.pro-view-card--active');
    expect(text(card)).toContain('Pro, no end date.');
    expect(root.querySelector('[data-pro-checkout]')).toBeNull();
    expect(hasManage(root)).toBe(false);
  });

  it('dev server: dev card first (Pro sim, ads on), real plan, then pitch preview', async () => {
    const { root } = await renderAccount('dev');
    const dev = root.querySelector('.pro-view-card--dev');
    expect(root.firstElementChild).toBe(dev);
    expect(text(dev)).toContain('Pro features are switched on here');
    expect(text(dev)).toContain('Ads and sponsored slots stay visible on purpose');
    expect(text(dev)).toContain('Pro, no end date.');
    expect(root.querySelector('.pro-view-funnel')).toBeTruthy();
  });

  it.each(Object.keys(ACCOUNTS))('%s: no em dash in rendered copy', async (type) => {
    const { root } = await renderAccount(type);
    expect(root.textContent).not.toContain('\u2014');
  });
});

/** Run the daily cron rule on one account. */
function cron(meta, day) {
  return compExpired(meta, at(day)) ? expireCompMeta(meta) : meta;
}
function at(day) {
  return new Date(`${day}T12:00:00Z`);
}
const pay = (meta, day) => applyPaidEntitlement(meta, 'pro', { now: at(day) }).meta;
const cancel = (meta, day) => applyPaidEntitlement(meta, 'free', { now: at(day) }).meta;

describe('entitlement lifecycle by account type', () => {
  it('beta tester who never pays: Pro through Mar 31, free from Apr 1', () => {
    let meta = { plan: 'pro', comp_until: '2027-03-31' };
    meta = cron(meta, '2027-03-31');
    expect(meta.plan).toBe('pro');
    meta = cron(meta, '2027-04-01');
    expect(meta).toEqual({ plan: 'free' });
  });

  it('beta tester who pays mid-beta: survives the cron, then gets unused days after cancelling', () => {
    let meta = { plan: 'pro', comp_until: '2027-03-31' };
    meta = pay(meta, '2027-01-01');
    meta = cron(meta, '2027-04-01');
    expect(meta.plan).toBe('pro');
    meta = pay(meta, '2027-05-01');
    expect(meta.paid_since).toBe('2027-01-01');
    meta = cancel(meta, '2027-06-01');
    expect(meta).toEqual({ plan: 'pro', comp_until: '2027-08-29' });
    expect(cron(meta, '2027-08-29').plan).toBe('pro');
    expect(cron(meta, '2027-08-30')).toEqual({ plan: 'free' });
  });

  it('beta tester who pays after the beta ended: no credit, free on cancel', () => {
    let meta = cron({ plan: 'pro', comp_until: '2027-03-31' }, '2027-04-01');
    meta = pay(meta, '2027-05-01');
    expect(meta.plan).toBe('pro');
    meta = cancel(meta, '2027-07-01');
    expect(meta).toEqual({ plan: 'free' });
  });

  it('extended beta (make-good to May 31) keeps Pro past the cohort date', () => {
    const meta = { plan: 'pro', comp_until: '2027-05-31' };
    expect(cron(meta, '2027-04-01').plan).toBe('pro');
    expect(cron(meta, '2027-06-01').plan).toBe('free');
  });

  it('paying subscriber with no beta: cron never touches, free right after cancel', () => {
    let meta = pay({}, '2027-01-01');
    expect(cron(meta, '2030-01-01')).toBe(meta);
    meta = cancel(meta, '2027-02-01');
    expect(meta).toEqual({ plan: 'free' });
  });

  it('permanent comp: cron never touches', () => {
    const meta = { plan: 'pro', beta: true };
    expect(cron(meta, '2030-01-01')).toBe(meta);
  });

  it('out-of-order Polar retry cannot re-grant a cancelled subscriber', () => {
    let meta = applyPaidEntitlement({}, 'pro', { eventAt: '2027-01-01T00:00:00Z', now: at('2027-01-01') }).meta;
    meta = applyPaidEntitlement(meta, 'free', { eventAt: '2027-02-01T00:00:00Z', now: at('2027-02-01') }).meta;
    const retry = applyPaidEntitlement(meta, 'pro', { eventAt: '2027-01-01T00:00:00Z', now: at('2027-02-02') });
    expect(retry.stale).toBe(true);
    expect(retry.meta.plan).toBe('free');
  });
});
