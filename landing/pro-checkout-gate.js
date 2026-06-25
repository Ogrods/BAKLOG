/**
 * Hide Polar checkout CTAs on baklog.app when BAKLOG_PRO_CHECKOUT is not set on Vercel.
 * Fetches GET /api/pro-config (landing/api/pro-config.js).
 */
(function proCheckoutGate() {
  const BETA_NOTE =
    "Checkout is closed during beta. Pro perks will roll out to beta testers before public launch.";

  function stripCheckoutLinks(root) {
    root.querySelectorAll("a.pro-checkout-link").forEach((a) => {
      const span = document.createElement("span");
      span.className = "pro-checkout-beta-inline";
      span.textContent = a.textContent || "Support BAKLOG";
      a.replaceWith(span);
    });
  }

  function apply(enabled) {
    if (enabled) return;
    document.querySelectorAll("[data-pro-checkout]").forEach((el) => {
      el.innerHTML = `<p class="pro-checkout-beta-note">${BETA_NOTE}</p>`;
    });
    stripCheckoutLinks(document);
  }

  async function init() {
    let enabled = false;
    try {
      const res = await fetch("/api/pro-config", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        enabled = !!data.proCheckoutEnabled;
      }
    } catch (_) {
      /* offline preview: treat as beta (checkout off) */
    }
    apply(enabled);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
