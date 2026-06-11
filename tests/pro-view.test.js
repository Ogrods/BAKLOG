import { describe, expect, it, vi, beforeEach } from 'vitest';
import { isProPromoSponsorId, proPromoBannerHtml, PRO_PROMO_ITEM } from '../js/sponsored-deals.js';

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
    document.body.innerHTML = '<div id="proViewRoot"></div>';
  });

  it('renders buy buttons and license field for free local users', async () => {
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    const root = document.getElementById('proViewRoot');
    expect(root.innerHTML).toContain('Get Pro — $5/mo');
    expect(root.innerHTML).toContain('buy.polar.sh');
    expect(root.querySelector('[data-pro-license-form]')).toBeTruthy();
  });

  it('shows active state for Pro users', async () => {
    const authGate = await import('../js/auth-gate.js');
    authGate.isPro.mockReturnValue(true);
    const { renderProView } = await import('../js/pro-view.js');
    renderProView();
    expect(document.getElementById('proViewRoot').textContent).toContain("You're on Pro");
  });
});
