// Public Pro rollout config for the marketing site + local app parity.
// Set BAKLOG_PRO_CHECKOUT=1 on Vercel when Polar checkout should be live.
// Sync checkout URLs with shared/pro_checkout.py + js/pro-checkout.js.

const PRO_CHECKOUT_MONTHLY =
  "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw";
const PRO_CHECKOUT_YEARLY =
  "https://buy.polar.sh/polar_cl_EluZmAQP7KUeeSQfnVfEwML7NdbrW3ruDy4SB364dE3";

function proCheckoutEnabled() {
  const raw = String(process.env.BAKLOG_PRO_CHECKOUT || "0").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

export default {
  async fetch() {
    const enabled = proCheckoutEnabled();
    return Response.json(
      {
        proCheckoutEnabled: enabled,
        proCheckout: enabled
          ? { monthly: PRO_CHECKOUT_MONTHLY, yearly: PRO_CHECKOUT_YEARLY }
          : { monthly: "", yearly: "" },
      },
      {
        headers: { "Cache-Control": "no-store" },
      },
    );
  },
};
