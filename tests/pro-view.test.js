import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { isProPromoSponsorId, proPromoBannerHtml, PRO_PROMO, PRO_PROMO_ITEM } from '../js/sponsored-deals.js';

vi.mock('../js/auth-gate.js', () => ({
  isPro: vi.fn(() => false),
  isAccountAuthMode: vi.fn(() => false),
  isLocalProfilesEnabled: vi.fn(() => false),
  licenseActivationEnabled: vi.fn(() => true),
  proCheckoutEnabled: vi.fn(() => true),
  proCheckoutUrls: vi.fn(() => ({})),
  getAccountEmail: vi.fn(() => ''),
  getAccountProfileId: vi.fn(() => ''),
  refreshAccountPlan: vi.fn(async () => 'free'),
}));

vi.mock('../js/filters-ui.js', () => ({ switchView: vi.fn() }));
vi.mock('../js/prefs.js', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, savePrefs: vi.fn() };
});

describe('isProPromoSponsorId', () => {
  it('recognizes house Pro promo ids', () => {
    expect(isProPromoSponsorId('house-pro-promo')).toBe(true);
    expect(isProPromoSponsorId('house-spotlight-pro-logo')).toBe(true);
    expect(isProPromoSponsorId('house-lib-backlog')).toBe(true);
    expect(isProPromoSponsorId('house-spotlight-library')).toBe(true);
    expect(isProPromoSponsorId('house-support-baklog')).toBe(true);
    expect(isProPromoSponsorId('house-itch-privacy')).toBe(true);
  });
});

describe('proPromoBannerHtml', () => {
  it('does not render the stale Planned badge', () => {
    const html = proPromoBannerHtml(PRO_PROMO_ITEM);
    expect(html).toContain('BAKLOG Pro');
    expect(html).not.toContain('>Planned<');
  });
});

describe('renderProView', () => {
  beforeEach(async () => {
    document.body.innerHTML = '<div id="proContainer"><div id="proViewRoot"></div></div>';
    const authGate = await import('../js/auth-gate.js');
    authGate.licenseActivationEnabled.mockReturnValue(true);
    authGate.proCheckoutEnabled.mockReturnValue(true);
  });

  it('renders conversion funnel with hero banner, toggle, six perks, and license field', async () => {
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    const root = document.getElementById('proViewRoot');
    expect(root.innerHTML).toContain(PRO_PROMO.title);
    expect(root.querySelector('[data-pro-checkout]')?.textContent).toContain('Support BAKLOG');
    expect(root.innerHTML).not.toMatch(/\$5\s*\/\s*mo/i);
    expect(root.innerHTML).toContain('buy.polar.sh');
    expect(root.querySelector('[data-pro-hero-banner]')).toBeTruthy();
    expect(root.querySelector('[data-pro-hero-banner]')?.getAttribute('src')).toContain('baklog-pro-polar-yearly');
    expect(root.querySelector('.pro-view-funnel--yearly')).toBeTruthy();
    expect(root.querySelector('[data-pro-plan="monthly"]')).toBeTruthy();
    expect(root.querySelector('[data-pro-plan="yearly"]')).toBeTruthy();
    expect(root.querySelector('[data-pro-checkout]')).toBeTruthy();
    expect(root.querySelector('.pro-view-compare')).toBeTruthy();
    expect(root.querySelector('.pro-view-trust-list')).toBeTruthy();
    expect(root.querySelectorAll('.pro-view-perk')).toHaveLength(PRO_PROMO.features.length);
    expect(root.querySelector('[data-pro-license-form]')).toBeTruthy();
  });

  it('shows license field and refresh even when license activation is disabled in config', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.licenseActivationEnabled.mockReturnValue(false);
    authGate.proCheckoutEnabled.mockReturnValue(false);
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    const root = document.getElementById('proViewRoot');
    expect(root.querySelector('[data-pro-license-form]')).toBeNull();
    expect(root.querySelector('[data-pro-refresh]')).toBeTruthy();
    expect(root.innerHTML).toContain('BAKLOG_POLAR_ORG_ID');
  });

  it('hides checkout CTAs when proCheckoutEnabled is false', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.proCheckoutEnabled.mockReturnValue(false);
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    const root = document.getElementById('proViewRoot');
    expect(root.querySelector('[data-pro-checkout]')).toBeNull();
    expect(root.innerHTML).toContain('Checkout is closed during beta');
  });

  it('switches checkout label and hero banner when monthly plan is selected', async () => {
    const { renderProView, wireProView } = await import('../js/pro-view.js');
    wireProView();
    renderProView();
    const root = document.getElementById('proViewRoot');
    root.querySelector('[data-pro-plan="monthly"]')?.click();
    expect(root.querySelector('[data-pro-checkout]')?.textContent).toContain('Support BAKLOG');
    expect(root.innerHTML).not.toMatch(/\$5\s*\/\s*mo/i);
    expect(root.querySelector('[data-pro-hero-banner]')?.getAttribute('src')).toContain('baklog-pro-polar.png');
    expect(root.querySelector('.pro-view-funnel--monthly')).toBeTruthy();
  });

  it('shows active state for Pro users', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isPro.mockReturnValue(true);
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    expect(document.getElementById('proViewRoot').textContent).toContain("You're on Pro");
  });
});

describe('post-checkout return', () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = `
      <div id="proContainer">
        <div id="proViewRoot"></div>
        <p id="proViewStatus" class="pro-view-status" hidden></p>
        <input id="proViewLicenseKey" type="text" />
      </div>`;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('consumeCheckoutQuery strips checkout params and targets Pro view', async () => {
    const replaceState = vi.fn();
    vi.stubGlobal('history', { replaceState });
    vi.stubGlobal('location', {
      href: 'http://127.0.0.1:8765/?checkout=success&checkout_id=ord_1',
      search: '?checkout=success&checkout_id=ord_1',
      pathname: '/',
    });
    const { consumeCheckoutQuery } = await import('../js/pro-view.js');
    const { state } = await import('../js/state.js');
    const { loadActiveView } = await import('../js/prefs.js');
    expect(consumeCheckoutQuery()).toBe(true);
    expect(replaceState).toHaveBeenCalledWith({}, '', '/');
    expect(loadActiveView()).toBe('pro');
    expect(state.activeView).toBe('pro');
  });

  it('handleCheckoutSuccessReturn reloads when hosted auth plan is pro', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.refreshAccountPlan.mockResolvedValue('pro');
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    const { markCheckoutSuccessPending, handleCheckoutSuccessReturn } = await import('../js/pro-view.js');
    const { proWelcomeSessionKey } = await import('../js/profiles.js');
    markCheckoutSuccessPending();
    await handleCheckoutSuccessReturn();
    expect(authGate.refreshAccountPlan).toHaveBeenCalled();
    expect(document.getElementById('proViewStatus').textContent).toContain('Pro is active');
    expect(sessionStorage.getItem(proWelcomeSessionKey())).toBe('1');
    vi.advanceTimersByTime(500);
    expect(reload).toHaveBeenCalled();
  });

  it('handleCheckoutSuccessReturn prompts refresh when webhook lags', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.refreshAccountPlan.mockResolvedValue('free');
    const { markCheckoutSuccessPending, handleCheckoutSuccessReturn } = await import('../js/pro-view.js');
    markCheckoutSuccessPending();
    await handleCheckoutSuccessReturn();
    expect(document.getElementById('proViewStatus').textContent).toContain('Payment received');
  });

  it('handleCheckoutSuccessReturn focuses license key for local-only users', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isAccountAuthMode.mockReturnValue(false);
    authGate.licenseActivationEnabled.mockReturnValue(true);
    const input = document.getElementById('proViewLicenseKey');
    const focusSpy = vi.spyOn(input, 'focus');
    const { markCheckoutSuccessPending, handleCheckoutSuccessReturn } = await import('../js/pro-view.js');
    markCheckoutSuccessPending();
    await handleCheckoutSuccessReturn();
    expect(document.getElementById('proViewStatus').textContent).toContain('license key');
    expect(focusSpy).toHaveBeenCalled();
  });
});

describe('Pro activation UX', () => {
  beforeEach(() => {
    vi.resetModules();
    sessionStorage.clear();
    document.body.innerHTML = `
      <button type="button" class="view-tab" data-view="pro"></button>
      <div id="proWelcomeBanner" class="migration-banner pro-welcome-banner hidden"></div>`;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it('applyProTabVisibility keeps Pro tab visible during checkout pending even when isPro', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isPro.mockReturnValue(true);
    const { state } = await import('../js/state.js');
    state.activeView = 'pro';
    const { markCheckoutSuccessPending, applyProTabVisibility } = await import('../js/pro-view.js');
    markCheckoutSuccessPending();
    applyProTabVisibility();
    const tab = document.querySelector('.view-tab[data-view="pro"]');
    expect(tab.classList.contains('hidden')).toBe(false);
  });

  it('showProWelcomeBanner renders once when flag is set and user is Pro', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isPro.mockReturnValue(true);
    const { showProWelcomeBanner } = await import('../js/pro-view.js');
    const { proWelcomeSessionKey } = await import('../js/profiles.js');
    sessionStorage.setItem(proWelcomeSessionKey(), '1');
    showProWelcomeBanner();
    const banner = document.getElementById('proWelcomeBanner');
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.textContent).toContain("You're on Pro");
    expect(sessionStorage.getItem(proWelcomeSessionKey())).toBeNull();
    banner.querySelector('.pro-welcome-dismiss')?.click();
    expect(banner.classList.contains('hidden')).toBe(true);
  });
});
