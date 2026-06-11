import { describe, expect, it, vi, beforeEach } from 'vitest';
import { isProPromoSponsorId, proPromoBannerHtml, PRO_PROMO, PRO_PROMO_ITEM } from '../js/sponsored-deals.js';

vi.mock('../js/auth-gate.js', () => ({
  isPro: vi.fn(() => false),
  isAccountAuthMode: vi.fn(() => false),
  licenseActivationEnabled: vi.fn(() => true),
  proCheckoutUrls: vi.fn(() => ({})),
  getAccountEmail: vi.fn(() => ''),
  refreshAccountPlan: vi.fn(async () => 'free'),
}));

describe('isProPromoSponsorId', () => {
  it('recognizes house Pro promo ids', () => {
    expect(isProPromoSponsorId('house-pro-promo')).toBe(true);
    expect(isProPromoSponsorId('house-spotlight-pro-logo')).toBe(true);
    expect(isProPromoSponsorId('house-lib-backlog')).toBe(true);
    expect(isProPromoSponsorId('house-spotlight-library')).toBe(true);
    expect(isProPromoSponsorId('house-support-baklog')).toBe(false);
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
  beforeEach(() => {
    document.body.innerHTML = '<div id="proContainer"><div id="proViewRoot"></div></div>';
  });

  it('renders conversion funnel with toggle, six perks, and license field', async () => {
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    const root = document.getElementById('proViewRoot');
    expect(root.innerHTML).toContain(PRO_PROMO.title);
    expect(root.innerHTML).toContain('Get Pro — $5/mo');
    expect(root.innerHTML).toContain('buy.polar.sh');
    expect(root.querySelector('[data-pro-plan="monthly"]')).toBeTruthy();
    expect(root.querySelector('[data-pro-plan="yearly"]')).toBeTruthy();
    expect(root.querySelector('[data-pro-checkout]')).toBeTruthy();
    expect(root.querySelector('.pro-view-compare')).toBeTruthy();
    expect(root.querySelector('.pro-view-trust-list')).toBeTruthy();
    expect(root.querySelectorAll('.pro-view-perk')).toHaveLength(PRO_PROMO.features.length);
    expect(root.querySelector('[data-pro-license-form]')).toBeTruthy();
  });

  it('switches checkout label when yearly plan is selected', async () => {
    const { renderProView, wireProView } = await import('../js/pro-view.js');
    wireProView();
    renderProView();
    const root = document.getElementById('proViewRoot');
    root.querySelector('[data-pro-plan="yearly"]')?.click();
    expect(root.querySelector('[data-pro-checkout]')?.textContent).toContain('$50/yr');
  });

  it('shows active state for Pro users', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isPro.mockReturnValue(true);
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    expect(document.getElementById('proViewRoot').textContent).toContain("You're on Pro");
  });
});
