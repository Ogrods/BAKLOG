import { describe, expect, it } from 'vitest';
import { buildProCheckoutUrl, PRO_CHECKOUT_MONTHLY } from '../js/pro-checkout.js';

describe('buildProCheckoutUrl', () => {
  it('returns empty for missing base', () => {
    expect(buildProCheckoutUrl('')).toBe('');
  });

  it('prefills email and external customer id', () => {
    const url = buildProCheckoutUrl(PRO_CHECKOUT_MONTHLY, {
      email: 'buyer@example.com',
      externalId: '11111111-1111-4111-8111-111111111111',
    });
    const u = new URL(url);
    expect(u.searchParams.get('customer_email')).toBe('buyer@example.com');
    expect(u.searchParams.get('external_customer_id')).toBe('11111111-1111-4111-8111-111111111111');
  });

  it('leaves base url unchanged when no prefill opts', () => {
    expect(buildProCheckoutUrl(PRO_CHECKOUT_MONTHLY)).toBe(PRO_CHECKOUT_MONTHLY);
  });
});
