/** Polar checkout links — sync with shared/pro_checkout.py + landing/index.html. */
export const PRO_CHECKOUT_MONTHLY =
  'https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw';
export const PRO_CHECKOUT_YEARLY =
  'https://buy.polar.sh/polar_cl_EluZmAQP7KUeeSQfnVfEwML7NdbrW3ruDy4SB364dE3';

/**
 * Append Polar checkout-link prefill params so hosted-auth buyers match the
 * webhook (external_customer_id = Supabase user id, customer_email locked).
 *
 * @param {string} baseUrl
 * @param {{ email?: string, externalId?: string }} [opts]
 * @returns {string}
 */
export function buildProCheckoutUrl(baseUrl, { email = '', externalId = '' } = {}) {
  if (!baseUrl || typeof baseUrl !== 'string') return '';
  try {
    const u = new URL(baseUrl.trim());
    const mail = String(email || '').trim();
    const ext = String(externalId || '').trim();
    if (mail) u.searchParams.set('customer_email', mail);
    if (ext) u.searchParams.set('external_customer_id', ext);
    return u.toString();
  } catch {
    return baseUrl;
  }
}
